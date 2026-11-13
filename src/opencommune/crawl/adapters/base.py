"""Adapters are pure: page content in, links out. The crawl driver in crawl/fetch.py does all HTTP.

Every adapter subclasses `ListingAdapter`, which supplies defaults for the hooks so the driver calls
them without checking whether an adapter defines them:

- `listing_urls(source)` builds the entry URLs from the source config. The default uses
  `source.listing_urls` verbatim; API adapters add query parameters.
- `request(step, url)` is the request for one page, a plain GET by default. Override it for a POST
  body or extra headers. The driver merges its own default headers (User-Agent, Accept-Language)
  into the request before sending it.
- `extract_links(content, base_url, step, date_regex, date_order, parent=None)` returns the links on
  one page. `parent` is the link that led to this page (None on the first hop); a document without a
  date of its own inherits the parent's, see `Link.context_date`.
- `next_url(content, url, step, headers=None)` returns the next page of a paginated listing, or None.
  The driver follows it until None, within the step's `max_follow`. `headers` are the response
  headers when the driver has them (WordPress reports the page count in `X-WP-Total`).

`AdapterStep.kind` lets a multi-hop API adapter name its hops in the config instead of sniffing the
page URL.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import httpx

from ...schemas import AdapterStep, SourceConfig


@dataclass(frozen=True)
class Link:
    url: str
    text: str
    date: dt.date | None = None
    upstream_id: str | None = None
    # "month" when the listing gives only month and year; `date` is then the first of that month.
    date_precision: Literal["day", "month"] = "day"
    # Set when `date` did not come from the link itself but from its surroundings: the enclosing
    # table row or list item, or the link of the previous hop that led to this page.
    context_date: dt.date | None = None


class ListingAdapter:
    """Base class with the default hooks. Subclasses set `name` and implement `extract_links`."""

    name: str = "base"

    def listing_urls(self, source: SourceConfig) -> list[str]:
        return list(source.listing_urls)

    def request(self, step: AdapterStep, url: str) -> httpx.Request:
        return httpx.Request("GET", url)

    def extract_links(
        self,
        html: str,
        base_url: str,
        step: AdapterStep,
        date_regex: str | None,
        date_order: str,
        parent: Link | None = None,
    ) -> list[Link]:
        raise NotImplementedError

    def next_url(
        self, content: str, url: str, step: AdapterStep, headers: Mapping[str, str] | None = None
    ) -> str | None:
        return None
