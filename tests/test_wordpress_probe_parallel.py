"""Offline checks for network-scoped availability probes and resumable reporting."""

import datetime as dt
import importlib.util
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from opencommune.config import settings
from opencommune.crawl import http

spec = importlib.util.spec_from_file_location(
    "wordpress_probe", Path(__file__).resolve().parents[1] / "scripts" / "probe_wordpress.py"
)
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)


@pytest.fixture(autouse=True)
def isolated_cooldowns(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)


def entry(bfs_id, host):
    return SimpleNamespace(bfs_id=bfs_id, name=host, canton="VD", website=f"https://{host}")


def test_workers_serialize_each_network_and_preserve_every_result(tmp_path, monkeypatch):
    mapping = {"a.test": "1.2.3", "b.test": "1.2.3", "c.test": "4.5.6"}
    monkeypatch.setattr(http.Politeness, "_network", lambda self, host: mapping[host])
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active = set()
    order = []

    def fake_probe(e, client, polite):
        with lock:
            assert polite.network not in active
            assert polite.delay >= 2
            active.add(polite.network)
            order.append(e.bfs_id)
        if e.bfs_id in {1, 3}:
            barrier.wait(timeout=5)  # different networks must actually run concurrently
        with lock:
            active.remove(polite.network)
        return {"bfs_id": e.bfs_id, "status": "available"}

    monkeypatch.setattr(wp, "probe", fake_probe)
    path = tmp_path / "probe.json"
    results = {"99": {"status": "empty"}}
    wp.scan([entry(1, "a.test"), entry(2, "b.test"), entry(3, "c.test")], results, path, workers=4)
    assert order.index(1) < order.index(2)
    assert set(results) == {"1", "2", "3", "99"}
    assert json.loads(path.read_text()) == results
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize("redirect_robots", [False, True])
@pytest.mark.parametrize("target_host", ["www.example.test", "external.test"])
def test_redirect_is_deferred_before_contact_including_robots(
    monkeypatch, redirect_robots, target_host
):
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    networks = {"example.test": "1.2.3", "www.example.test": "4.5.6", "external.test": "1.2.3"}
    monkeypatch.setattr(http.Politeness, "_network", lambda self, host: networks[host])
    calls = []

    def answer(request):
        calls.append(str(request.url))
        if request.url.path == "/robots.txt" and not redirect_robots:
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(302, headers={"location": f"https://{target_host}{request.url.path}"})

    with http.make_client(httpx.MockTransport(answer)) as client:
        polite = wp.ScopedPoliteness(client, "1.2.3")
        polite.website = "https://example.test"
        result = wp.probe(entry(1, "example.test"), client, polite)
    assert result["status"] == "deferred_network"
    assert all(httpx.URL(u).host == "example.test" for u in calls)
    assert len(calls) == (1 if redirect_robots else 2)


def test_same_network_origin_redirect_is_allowed(monkeypatch):
    monkeypatch.setattr(http.Politeness, "wait", lambda self, url: None)
    monkeypatch.setattr(http.Politeness, "_network", lambda self, host: "1.2.3")

    def answer(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.host == "example.test":
            return httpx.Response(
                302, headers={"location": "https://www.example.test/wp-json/wp/v2/media"}
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "mime_type": "application/pdf",
                    "source_url": "https://www.example.test/a.pdf",
                }
            ],
            headers={"x-wp-total": "1"},
        )

    with http.make_client(httpx.MockTransport(answer)) as client:
        polite = wp.ScopedPoliteness(client, "1.2.3")
        polite.website = "https://example.test"
        assert wp.probe(entry(1, "example.test"), client, polite)["status"] == "available"


def test_sequential_retry_policy_and_order_remain_unchanged(tmp_path, monkeypatch):
    now = dt.datetime.now(dt.UTC).isoformat()
    results = {
        "1": {"status": "available"},
        "2": {"status": "empty"},
        "3": {"status": "http_error", "retry_after": "3600", "checked_at": now},
        "4": {
            "status": "http_error",
            "retry_after": "Fri, 11 Sep 2026 23:00:00 GMT",
            "checked_at": now,
        },
        "5": {"status": "deferred_network"},
    }
    calls = []

    def fake_probe(e, client, polite):
        calls.append(e.bfs_id)
        assert polite.network is None
        return {"status": "empty"}

    monkeypatch.setattr(wp, "probe", fake_probe)
    entries = [entry(i, f"host{i}.test") for i in range(1, 7)]
    wp.scan(entries, results, tmp_path / "report.json")
    assert calls == [6]
    wp.scan(entries, results, tmp_path / "report.json", retry_failed=True)
    assert calls == [6, 5]


def test_limiter_waits_two_seconds_across_same_network_hosts(monkeypatch):
    clock = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(http.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(http.time, "sleep", sleep)
    monkeypatch.setattr(http.Politeness, "_network_last", {})
    monkeypatch.setattr(http.Politeness, "_network", lambda self, host: "1.2.3")
    with http.make_client(httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        polite = wp.ScopedPoliteness(client, "1.2.3")
        polite.website = "https://a.test"
        polite.wait("https://a.test/robots.txt")
        polite.website = "https://b.test"
        polite.wait("https://b.test/robots.txt")
    assert sleeps == [polite.delay]
    assert polite.delay >= 2.0
