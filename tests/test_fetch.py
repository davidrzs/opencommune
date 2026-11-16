import time

import httpx

from opencommune.crawl.http import Politeness, RobotsRules


def test_politeness_limits_per_network_not_only_per_host(monkeypatch):
    p = Politeness(httpx.Client(), delay=0.2, user_agent="test")
    monkeypatch.setattr(p, "_network", lambda host: "10.0.0")  # every host on one network
    Politeness._network_last.clear()
    t = time.monotonic()
    p.wait("https://a.example.ch/x")
    p.wait("https://b.example.ch/y")  # different host, same network: must still wait
    assert time.monotonic() - t >= 0.2


def test_politeness_hosts_on_different_networks_do_not_wait(monkeypatch):
    p = Politeness(httpx.Client(), delay=0.3, user_agent="test")
    monkeypatch.setattr(p, "_network", lambda host: host)
    Politeness._network_last.clear()
    t = time.monotonic()
    p.wait("https://a.example.ch/x")
    p.wait("https://b.example.ch/y")
    assert time.monotonic() - t < 0.25


def test_politeness_threads_on_different_hosts_do_not_serialise(monkeypatch):
    """A thread pausing for one host must not hold the lock while it sleeps."""
    import threading

    p = Politeness(httpx.Client(), delay=0.3, user_agent="test")
    monkeypatch.setattr(p, "_network", lambda host: host)
    Politeness._network_last.clear()

    def twice(host: str) -> None:
        p.wait(f"https://{host}/x")
        p.wait(f"https://{host}/y")  # the second call on a host sleeps for the delay

    threads = [threading.Thread(target=twice, args=(h,)) for h in ("a.ch", "b.ch", "c.ch")]
    t = time.monotonic()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert time.monotonic() - t < 0.55  # serialised sleeps would take about 0.9 s


def test_host_crawl_delay_does_not_slow_the_rest_of_its_network(monkeypatch):
    """A host asking for a long Crawl-delay waits alone; other hosts on the same /24 keep the
    one-second cadence."""
    p = Politeness(httpx.Client(), delay=0.1, user_agent="test")
    monkeypatch.setattr(p, "_network", lambda host: "10.0.0")
    Politeness._network_last.clear()
    p._crawl_delay["slow.example.ch"] = 0.8
    p.wait("https://slow.example.ch/a")  # first request goes out at once
    t = time.monotonic()
    p.wait("https://fast.example.ch/b")  # same network, must only wait the network delay
    assert time.monotonic() - t < 0.3
    t = time.monotonic()
    p.wait("https://slow.example.ch/c")  # the slow host itself does wait
    assert time.monotonic() - t >= 0.6


def test_robots_crawl_delay_is_honoured(monkeypatch):
    p = Politeness(httpx.Client(), delay=0.1, user_agent="TractandaBot/0.1")
    monkeypatch.setattr(p, "_network", lambda host: host)
    Politeness._network_last.clear()
    rules = RobotsRules("User-agent: *\nCrawl-delay: 1\nDisallow: /private\n", "TractandaBot/0.1")
    p._robots["slow.example.ch"] = rules
    p._crawl_delay["slow.example.ch"] = rules.crawl_delay
    assert p.allowed("https://slow.example.ch/x") and not p.allowed(
        "https://slow.example.ch/private/y"
    )
    t = time.monotonic()
    p.wait("https://slow.example.ch/a")
    p.wait("https://slow.example.ch/b")
    assert time.monotonic() - t >= 1.0


def test_robots_wildcards_and_agent_groups():
    text = """
User-agent: Googlebot
Disallow: /nothing-for-us

User-agent: *
Disallow: /*.pdf$
Disallow: /images/
Allow: /images/public/
Crawl-delay: 10
"""
    r = RobotsRules(text, "TractandaBot/0.1 (+https://www.tractanda.ch)")
    assert not r.allowed("https://x.ch/docs/pv-2024.pdf")  # wildcard plus end anchor
    assert r.allowed(
        "https://x.ch/docs/pv-2024.pdf?download=1"
    )  # anchor: the query breaks the match
    assert not r.allowed("https://x.ch/images/a.pdf") and r.allowed(
        "https://x.ch/images/public/a.jpg"
    )  # longest rule wins
    assert r.allowed("https://x.ch/nothing-for-us") and r.crawl_delay == 10.0
    ours = RobotsRules(
        "User-agent: TractandaBot\nDisallow: /\n\nUser-agent: *\nDisallow:\n",
        "TractandaBot/0.1",
    )
    assert not ours.allowed("https://x.ch/anything")


def test_a_refusal_written_for_the_former_name_still_binds_the_crawler():
    former = RobotsRules(
        "User-agent: OpenCommuneBot\nDisallow: /\n\nUser-agent: *\nDisallow:\n",
        "TractandaBot/0.1",
    )
    assert not former.allowed("https://x.ch/anything")
    assert former.refusing_rule("https://x.ch/anything") == "/"
    # Both names have a group: each must allow the URL, and the longer Crawl-delay applies.
    both = RobotsRules(
        "User-agent: TractandaBot\nDisallow: /intern/\nCrawl-delay: 2\n\n"
        "User-agent: OpenCommuneBot\nDisallow: /archiv/\nCrawl-delay: 5\n\n"
        "User-agent: *\nDisallow:\n",
        "TractandaBot/0.1",
    )
    assert not both.allowed("https://x.ch/intern/a.pdf")
    assert not both.allowed("https://x.ch/archiv/a.pdf")
    assert both.allowed("https://x.ch/protokolle/a.pdf")
    assert both.crawl_delay == 5.0


def test_driver_passes_response_headers_and_parent_to_the_adapter(monkeypatch):
    import datetime as dt
    from typing import ClassVar

    from opencommune.crawl.adapters.base import Link, ListingAdapter
    from opencommune.crawl.fetch import _links_for_hop
    from opencommune.schemas import AdapterConfig, AdapterStep

    class Fake(ListingAdapter):
        name = "fake"
        seen_headers: ClassVar[list] = []
        seen_parents: ClassVar[list] = []

        def extract_links(self, html, base_url, step, date_regex, date_order, parent=None):
            self.seen_parents.append(parent)
            return [Link(url=base_url + "/doc.pdf", text="x", date=parent.date if parent else None)]

        def next_url(self, content, url, step, headers=None):
            self.seen_headers.append(dict(headers or {}))

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, text="<html></html>", headers={"X-WP-TotalPages": "3"})
    )
    client = httpx.Client(transport=transport)
    p = Politeness(client, delay=0.0, user_agent="TractandaBot/0.1")
    monkeypatch.setattr(p, "_network", lambda host: host)
    p._robots["x.ch"] = None
    parent = Link(url="https://x.ch/session", text="Sitzung", date=dt.date(2025, 3, 10))
    out = _links_for_hop(
        "https://x.ch/session",
        Fake(),
        AdapterStep(selector="a"),
        AdapterConfig(steps=[AdapterStep(selector="a")]),
        client,
        p,
        parent,
    )
    assert Fake.seen_headers[0]["x-wp-totalpages"] == "3"
    assert Fake.seen_parents == [parent] and out[0].date == dt.date(2025, 3, 10)


def test_also_documents_takes_documents_from_the_listing_page(monkeypatch):
    from opencommune.crawl.fetch import discover
    from opencommune.schemas import AdapterConfig, AdapterStep, CommuneConfig

    pages = {
        "https://x.ch/gv": '<a href="/files/Protokoll GV 02.07.2026.pdf">Protokoll GV 02.07.2026</a> <a href="/node/1">Protokoll GV 22.04.2026</a>',
        "https://x.ch/node/1": '<a href="/files/Protokoll GV 22.04.2026.pdf">Protokoll GV 22.04.2026</a>',
    }
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200, text=pages.get(str(req.url), ""), headers={"content-type": "text/html"}
        )
    )
    client = httpx.Client(transport=transport)
    p = Politeness(client, delay=0.0, user_agent="TractandaBot/0.1")
    monkeypatch.setattr(p, "_network", lambda host: host)
    p._robots["x.ch"] = None
    cfg = AdapterConfig(
        steps=[
            AdapterStep(selector="a[href*='/node/']", text_regex="Protokoll", also_documents=True),
            AdapterStep(selector="a[href*='/files/']", text_regex="Protokoll"),
        ],
    )
    commune = CommuneConfig(
        bfs_id=1,
        name="X",
        canton="ZH",
        language="de",
        website="https://x.ch",
        body="assembly",
        listing_urls=["https://x.ch/gv"],
        adapter_config=cfg,
    )
    out = discover(commune, client, p)
    assert sorted(d.date.isoformat() for d in out.listed) == ["2026-04-22", "2026-07-02"]
