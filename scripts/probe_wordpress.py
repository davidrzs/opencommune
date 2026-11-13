"""Check registered WordPress PDF APIs resumably, optionally across hosting networks.

Run: uv run python scripts/probe_wordpress.py [--retry-failed]
The report is data/discovery/wordpress/probe.json (outside git), or probe-unclassified.json for
--scope unclassified (custom and unknown vendors). It records which APIs answer; it downloads no
PDFs and leaves the register unchanged.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from opencommune.config import settings
from opencommune.crawl import http
from opencommune.crawl.iweb import clean_url, same_site
from opencommune.register import load_register


class DeferredNetwork(Exception):
    """A target belongs outside this worker's permitted origin or hosting network."""


# The i-web hosting network, which the i-web collector crawls: a probe running beside it would
# exceed the per-network rate, so the probe leaves it out.
IWEB_NETWORK = "195.65.10"


class ScopedPoliteness(http.Politeness):
    def __init__(self, client, network=None, networks=None):
        super().__init__(client, max(2.0, settings.request_delay_seconds), settings.ua)
        self.network = network
        self.website = ""
        self._networks.update(networks or {})

    def guard(self, url):
        if not same_site(url, self.website):
            raise DeferredNetwork("external_redirect")
        network = self._network(urlsplit(url).netloc)
        if network == IWEB_NETWORK:
            raise DeferredNetwork("active_iweb_worker")
        if self.network is not None and network != self.network:
            raise DeferredNetwork("redirect_to_other_network")

    def allowed(self, url):
        self.guard(url)
        return super().allowed(url)

    def wait(self, url):
        # Robots redirects skip allowed(); guard every send before it reaches the client.
        self.guard(url)
        return super().wait(url)


def probe(entry, client, polite):
    origin = urlsplit(entry.website)
    query = urlencode(
        {
            "mime_type": "application/pdf",
            "per_page": 3,
            "page": 1,
            "_fields": "id,source_url,mime_type",
        }
    )
    endpoint = urlunsplit((origin.scheme, origin.netloc, "/wp-json/wp/v2/media", query, ""))
    result = dict(
        bfs_id=entry.bfs_id,
        name=entry.name,
        canton=entry.canton,
        website=entry.website,
        original_vendor=getattr(entry, "vendor", None),
        endpoint=endpoint,
        checked_at=dt.datetime.now(dt.UTC).isoformat(),
        sample_urls=[],
    )
    if polite._network(origin.netloc) == IWEB_NETWORK:
        return dict(result, status="deferred_network", reason="active_iweb_worker")
    try:
        if not polite.allowed(endpoint):
            return dict(result, status="robots")
        response = http._send(client, polite, client.build_request("GET", endpoint), stream=True)
        try:
            result["http_status"] = response.status_code
            if response.status_code != 200:
                return dict(
                    result, status="http_error", retry_after=response.headers.get("retry-after")
                )
            if not same_site(str(response.url), entry.website):
                return dict(result, status="invalid_response", reason="external_redirect")
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    return dict(result, status="invalid_response", reason="response_too_large")
            items = json.loads(body)
            if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
                return dict(result, status="invalid_response", reason="not_media_list")
            samples = [
                x["source_url"]
                for x in items
                if x.get("mime_type") == "application/pdf"
                and type(x.get("id")) is int
                and x["id"] > 0
                and isinstance(x.get("source_url"), str)
                and clean_url(x["source_url"])
            ]
            total = response.headers.get("x-wp-total", "")
            result["total"] = int(total) if total.isdigit() else None
            result["endpoint"] = str(response.url)
            result["sample_urls"] = samples
            status = "available" if samples else "empty" if not items else "invalid_response"
            return dict(result, status=status)
        finally:
            response.close()
    except DeferredNetwork as exc:
        return dict(result, status="deferred_network", reason=str(exc))
    except http.FetchFailure as exc:
        return dict(
            result,
            status=(
                "robots"
                if exc.kind == "robots"
                else "http_error"
                if exc.status is not None
                else "network_error"
            ),
            reason=exc.message,
            http_status=exc.status,
            retry_after=exc.retry_after,
        )
    except (ValueError, httpx.HTTPError) as exc:
        return dict(result, status="invalid_response", reason=str(exc))


def eligible(entry, results, retry_failed):
    previous = results.get(str(entry.bfs_id))
    if not previous:
        return True
    if not retry_failed or previous["status"] in {"available", "empty"}:
        return False
    retry = previous.get("retry_after")
    if retry:
        try:
            until = dt.datetime.fromisoformat(previous["checked_at"]) + dt.timedelta(
                seconds=int(retry)
            )
            if dt.datetime.now(dt.UTC) < until:
                return False
        except ValueError:
            return False  # date-form Retry-After: leave for review
    return True


def scan(entries, results, path, *, workers=1, retry_failed=False):
    """Each network has one sequential worker; report replacement is serialized separately."""
    if not 1 <= workers <= 4:
        raise ValueError("workers must be between 1 and 4")
    entries = [e for e in entries if eligible(e, results, retry_failed)]
    groups = defaultdict(list)
    networks = {}
    if workers == 1:
        groups[None] = entries  # preserve the original entry order for sequential probes
    else:
        with http.make_client() as client:
            resolver = http.Politeness(client, 2.0, settings.ua)
            for entry in entries:
                groups[resolver._network(urlsplit(entry.website).netloc)].append(entry)
            networks = resolver._networks.copy()
    save_lock = threading.Lock()

    def run_group(item):
        network, group = item
        with http.make_client() as client:
            client.timeout = httpx.Timeout(12.0, connect=8.0)
            polite = ScopedPoliteness(client, network, networks)
            for entry in group:
                polite.website = entry.website
                result = probe(entry, client, polite)
                with save_lock:
                    results[str(entry.bfs_id)] = result
                    part = path.with_suffix(".tmp")
                    part.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
                    part.replace(path)
                    print(
                        json.dumps(
                            {k: result.get(k) for k in ("bfs_id", "name", "status", "total")},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(run_group, groups.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--commune", help="Optional comma-separated BFS ids")
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--scope", choices=("wordpress", "unclassified"), default="wordpress")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    filename = "probe.json" if args.scope == "wordpress" else "probe-unclassified.json"
    path = settings.data_dir / "discovery/wordpress" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    results = json.loads(path.read_text()) if path.exists() else {}
    vendors = {"wordpress"} if args.scope == "wordpress" else {"custom", None}
    entries = [e for e in load_register() if e.vendor in vendors]
    if args.commune:
        wanted = {int(x) for x in args.commune.split(",")}
        entries = [e for e in entries if e.bfs_id in wanted]
    missing_website = sum(not e.website for e in entries)
    entries = [e for e in entries if e.website]
    # Availability probes make one attempt; 429s are recorded, never immediately retried.
    http.ATTEMPTS = 1
    scan(entries, results, path, workers=args.workers, retry_failed=args.retry_failed)
    print(
        json.dumps(
            {
                "scope": args.scope,
                "selected": len(entries),
                "missing_website": missing_website,
                "checked": len(results),
                "statuses": dict(Counter(x["status"] for x in results.values())),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
