"""Pydantic models for the crawler's configuration and the files it writes."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Body = Literal["assembly", "executive", "parliament", "commission"]
Lang = Literal["de", "fr", "it", "rm"]
# The website system behind a commune's site, as fingerprinted on the homepage or known from the
# vendor. `custom` is a hand-built site or a system seen once; `unknown` means nobody looked.
Vendor = Literal[
    "cmi-paris",
    "cmi-ratsinfo",
    "custom",
    "drupal",
    "govis",
    "i-web",
    "iomedia",
    "joomla",
    "megaphone",
    "neos",
    "onebyone",
    "onegov",
    "quicksite",
    "sh-cms",
    "typo3",
    "umbraco",
    "unknown",
    "weblication",
    "wordpress",
]


# --- discovery / fetch -------------------------------------------------------


class FormSubmit(BaseModel):
    """A listing reachable only by posting a form on the page (Bellinzona's older legislatures: a
    select inside `form#fric_11761`, ignored when sent as a GET). The page is fetched, the form's
    hidden inputs are copied (session tokens included), each `values` mapping is set on top, and
    the form is posted once per mapping; the step's selection runs on each response."""

    model_config = ConfigDict(extra="forbid")

    selector: str
    values: list[dict[str, str]] = Field(min_length=1)


class AdapterStep(BaseModel):
    """One hop in a listing crawl. Every step but the last yields pages to follow."""

    model_config = ConfigDict(extra="forbid")

    selector: str
    url_regex: str | None = None
    text_regex: str | None = None
    exclude_regex: str | None = None
    # Who approved the exclusion and when, for example "David 2026-11-20". Dropping documents by
    # their title is a coverage decision: lint-communes rejects an exclude_regex without it
    # (David, 2026-11-13).
    exclude_approved: str | None = None
    sort: Literal["none", "text_desc"] = "none"
    max_follow: int | None = None
    # Adapter-defined name of the hop, for multi-hop API adapters that would otherwise tell their hops
    # apart by the page URL.
    kind: str | None = None
    # "row": when the anchor's own text and URL give no title or date, take them from the enclosing
    # table row, list item or paragraph (a paragraph is cut at its line breaks). "heading": from the
    # nearest heading before the anchor (accordion pages with the meeting date in the section title).
    context: Literal["row", "heading"] | None = None
    # With a context: its date wins over the anchor's and the URL's, for file names that start with an
    # upload date (Arzier-Le Muids: 20260513_PV_23_... in the row of the session of 23.03.2026).
    prefer_context_date: bool = False
    # The last step's selector also runs on the pages of this hop: a listing that links the newest
    # document directly and older ones through sub-pages.
    also_documents: bool = False
    # CSS selector of the next-page link (`a[rel=next]`, `li.pager__item--next a`); the driver follows
    # it through the adapter's `next_url` until the page has none, within max_follow.
    next_selector: str | None = None
    # Attribute that holds the link on the selected elements instead of href, for sites that keep
    # document URLs in data attributes (Weblication `data-url`, WordPress Download Manager
    # `data-downloadurl`). Opt-in: other data attributes often point at scripts, not documents.
    url_attribute: str | None = None
    # Post this form on the page and read the responses instead of the page itself (see FormSubmit).
    form: FormSubmit | None = None
    # i-web embedded tables: append the row's date cell to link texts without a full date. Off where
    # that column is the publication date and the title names the period ("Mitteilungen des
    # Gemeinderates Januar 2022", Seegräben), so the title's month gives a month-precision date.
    table_row_dates: bool = True
    # What the last step's links lead to: PDF files, or decision pages published only as HTML,
    # stored as documents themselves. `content_selector` names the element that
    # holds the decisions; a page where it matches nothing is not stored.
    capture: Literal["pdf", "html"] = "pdf"
    content_selector: str | None = None

    @model_validator(mode="after")
    def _selector_with_html_capture(self) -> AdapterStep:
        if self.capture == "html" and not (self.content_selector or "").strip():
            raise ValueError("capture: html needs a content_selector")
        if self.capture == "pdf" and self.content_selector is not None:
            raise ValueError("content_selector applies only with capture: html")
        return self


class AdapterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[AdapterStep] = Field(min_length=1)
    date_regex: str | None = None
    date_order: Literal["dmy", "ymd"] = "dmy"
    max_follow: int = 3
    since_days: int | None = None
    volatile_params: list[str] = Field(
        default_factory=list
    )  # query parameters dropped from document URLs before they are remembered

    @model_validator(mode="after")
    def _capture_on_last_step(self) -> AdapterConfig:
        if any(step.capture != "pdf" for step in self.steps[:-1]):
            raise ValueError("capture: html applies only to the last step")
        return self


class SourceConfig(BaseModel):
    """One place to discover a commune's documents. A commune has a primary source (the top-level
    adapter fields, kept for the existing YAML) and optionally more under `sources`, for example
    an archive page for the history plus the current-year page."""

    model_config = ConfigDict(extra="forbid")

    adapter: str = "html_links"
    listing_urls: list[str]
    adapter_config: AdapterConfig
    body: Body | None = None
    vendor: Vendor | None = None


class CommuneConfig(BaseModel):
    """One entry of data/communes.yaml. Unknown keys are an error (`opencommune lint-communes`)."""

    model_config = ConfigDict(extra="forbid")

    bfs_id: int
    name: str
    canton: str
    language: Lang
    added: dt.date | None = None  # when the entry went into the configuration
    website: str
    body: Body
    vendor: Vendor = "unknown"
    listing_urls: list[str]
    adapter: str = "html_links"
    adapter_config: AdapterConfig
    sources: list[SourceConfig] = Field(default_factory=list)
    publicity_regime: str | None = None
    lat: float | None = None
    lon: float | None = None

    def all_sources(self) -> list[SourceConfig]:
        """Primary source first, then the extra ones, each with body and vendor filled in."""
        primary = SourceConfig(
            adapter=self.adapter,
            listing_urls=self.listing_urls,
            adapter_config=self.adapter_config,
            body=self.body,
            vendor=self.vendor,
        )
        extra = [
            s.model_copy(update={"body": s.body or self.body, "vendor": s.vendor or self.vendor})
            for s in self.sources
        ]
        return [primary, *extra]


class DocumentLink(BaseModel):
    url: str
    title: str
    date: dt.date | None = None
    body: Body | Literal["unknown"]
    listing_url: str
    adapter: str = "html_links"
    upstream_id: str | None = None
    date_precision: Literal["day", "month"] = (
        "day"  # "month" when the listing gave only month and year
    )


class RawSidecar(BaseModel):
    sha256: str
    source_url: str
    listing_url: str
    commune_bfs_id: int
    body: Body | Literal["unknown"]
    fetched_at: dt.datetime
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None
    size: int
    listing_title: str
    listing_date: dt.date | None = None
    adapter: str | None = (
        None  # None in sidecars written before sources existed: the commune's primary adapter
    )
    upstream_id: str | None = None
    date_precision: Literal["day", "month"] = "day"
    # HTML decision pages only: the step's selector, kept so that the page can be read again as
    # it was fetched, and the sha256 of that element's text with whitespace collapsed.
    content_selector: str | None = None
    content_sha256: str | None = None
