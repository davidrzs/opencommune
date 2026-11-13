"""Answer, for each URL, what the production crawler would do with it under robots.txt.

Uses fetch.Politeness, the code `opencommune fetch` runs, so a probe can never be stricter or looser
than the crawler: a robots.txt answered with 401, 403 or any other 4xx means no rules (allowed), a 429
or 5xx disallows the host for the run (RFC 9309, section 2.3.1). One robots.txt request per host, with
the usual pacing; the observation is recorded like any fetch.

    uv run python scripts/robots_check.py https://www.example.ch/protokolle/ [...]
"""

from __future__ import annotations

import argparse
import json

from opencommune.config import settings
from opencommune.crawl import http

MEANING = {
    "ok": "robots.txt read (or 404/410: no rules)",
    "restricted": "disallowed by a rule",
    "robots_unavailable": "robots.txt not readable: 4xx or unreachable means no rules, 5xx blocks",
    "rate_limited": "robots.txt answered 429: host blocked for this run",
}


def verdicts(polite: http.Politeness, urls: list[str]) -> list[dict]:
    out = []
    for url in urls:
        allowed = polite.allowed(url)
        status = polite.robots_status(url)
        if status == "ok" and not allowed:
            status = "restricted"
        out.append({"url": url, "allowed": allowed, "status": status, "meaning": MEANING[status]})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args()
    with http.make_client() as client:
        polite = http.Politeness(client, max(2, settings.request_delay_seconds), settings.ua)
        for row in verdicts(polite, args.urls):
            print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
