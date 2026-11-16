import datetime as dt
from types import SimpleNamespace

import httpx
import pytest

from opencommune.crawl import access, http


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(access.settings, "data_dir", tmp_path)
    monkeypatch.setattr(http.Politeness, "wait", lambda *args: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)
    return tmp_path


def check(body="", status=200, url="https://test.ch/docs/a.pdf"):
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, text=body))
    ) as client:
        return http.Politeness(client, 0, "TractandaBot/0.1").allowed(url)


def test_real_restriction_and_path_recovery(storage):
    assert not check("User-agent: *\nDisallow: /docs/\nAllow: /docs/public/")
    row = access.observations()[0]
    assert row["status"] == "restricted"
    assert row["rule"] == "/docs/"
    assert check(
        "User-agent: *\nDisallow: /docs/\nAllow: /docs/public/",
        url="https://test.ch/docs/public/a.pdf",
    )
    assert len(access.observations()) == 1
    assert check("User-agent: *\nAllow: /")
    assert access.observations() == []


@pytest.mark.parametrize("status,expected", [(429, "rate_limited"), (503, "robots_unavailable")])
def test_temporary_failure_is_not_explicit_restriction(storage, status, expected):
    assert not check(status=status)
    row = access.observations()[0]
    assert row["status"] == expected
    assert row["restricted_at"] is None


def test_failed_recheck_retains_evidence(storage):
    check("User-agent: *\nDisallow: /docs/")
    before = access.observations()[0]["restricted_at"]
    check(status=503)
    assert access.observations()[0]["restricted_at"] == before
    check("User-agent: *\nAllow: /")
    assert not access.observations()


def test_sites_are_attributed_to_one_commune_and_never_name_a_document(storage):
    access.record("https://test.ch/files/?token=secret", "restricted", rule="/files/")
    access.record("https://www.test.ch/files/applicant-name.pdf", "restricted")
    entries = [SimpleNamespace(bfs_id=1, name="Test", canton="VS", website="https://www.test.ch")]
    (site,) = access.by_commune(entries)[1]
    assert site["source_url"] in {"https://test.ch/", "https://www.test.ch/"}
    assert "secret" not in str(site) and "applicant" not in str(site)
    entries.append(
        SimpleNamespace(bfs_id=2, name="Other", canton="VS", website="https://test.ch/other")
    )
    assert access.by_commune(entries) == {}


def test_old_observation_is_stale(storage):
    access.record("https://test.ch/docs/", "restricted")
    import json

    path = next(access.directory().glob("*.json"))
    row = json.loads(path.read_text())
    row["restricted_at"] = (dt.datetime.now(dt.UTC) - dt.timedelta(days=8)).isoformat()
    path.write_text(json.dumps(row))
    entry = SimpleNamespace(bfs_id=1, name="Test", canton="VS", website="https://test.ch")
    assert access.stale(access.by_commune([entry])[1][0])


def test_request_failure_cannot_clear_robots_restriction(storage):
    url = "https://test.ch/docs/a.pdf"
    check("User-agent: *\nDisallow: /docs/")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as client:
        polite = http.Politeness(client, 0, "TractandaBot/0.1")
        http._send(client, polite, client.build_request("GET", url))
    assert {r["status"] for r in access.observations()} == {"restricted", "rate_limited"}
    access.record(url, "ok", channel="request")
    assert access.observations()[0]["status"] == "restricted"


def test_speculative_missing_page_is_not_access_restriction(storage):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
        polite = http.Politeness(client, 0, "TractandaBot/0.1")
        http._send(client, polite, client.build_request("GET", "https://test.ch/missing"))
    assert not access.observations()


def test_legacy_failures_are_only_recheck_candidates(storage):
    import json

    directory = storage / "discovery" / "iweb"
    directory.mkdir(parents=True)
    (directory / "1.json").write_text(
        json.dumps({"pages": {"https://test.ch/docs": {"kind": "robots"}}})
    )
    assert next(iter(access.checkpoint_candidates()))["url"] == "https://test.ch/docs"
    assert not access.observations()
