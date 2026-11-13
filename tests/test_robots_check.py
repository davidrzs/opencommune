import httpx
import pytest

from opencommune.crawl import access, http
from scripts.robots_check import verdicts


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(access.settings, "data_dir", tmp_path)
    monkeypatch.setattr(http.Politeness, "wait", lambda *args: None)
    monkeypatch.setattr(http, "ATTEMPTS", 1)


def run(status, body="", url="https://test.ch/protokolle/a.pdf"):
    transport = httpx.MockTransport(lambda r: httpx.Response(status, text=body))
    with httpx.Client(transport=transport) as client:
        return verdicts(http.Politeness(client, 0, "OpenCommuneBot/0.1"), [url])[0]


@pytest.mark.parametrize("status", [401, 403, 404, 410, 418])
def test_robots_4xx_is_no_block(status):
    assert run(status)["allowed"]


@pytest.mark.parametrize("status,expected", [(429, "rate_limited"), (503, "robots_unavailable")])
def test_robots_429_and_5xx_block(status, expected):
    row = run(status)
    assert not row["allowed"]
    assert row["status"] == expected


def test_rule_restriction_is_reported():
    row = run(200, "User-agent: *\nDisallow: /protokolle/")
    assert (row["allowed"], row["status"]) == (False, "restricted")
    assert run(200, "User-agent: *\nAllow: /")["allowed"]
