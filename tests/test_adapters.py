"""Date parsing and URL helpers of the html_links adapter. Recorded pages live in tests/fixtures."""

import datetime as dt
import pathlib
import re

import pytest

from opencommune.crawl.adapters.html_links import (
    HtmlLinksAdapter,
    parse_date,
    parse_date_with_url,
    unwrap_viewer,
)
from opencommune.schemas import AdapterStep

FIX = pathlib.Path(__file__).parent / "fixtures" / "html_links"


@pytest.mark.parametrize(
    "text,url,expected",
    [
        ("Einwohnerratssitzung 01/2025 vom 30. Januar 2025", "/_doc/1", "2025-01-30"),
        ("Verbale del 20.10.2025", "x", "2025-10-20"),
        ("4 février", "/seances/2026/4-fevrier/", "2026-02-04"),
        ("1er avril", "/seances/2026/1er-avril/", "2026-04-01"),
        ("", "/media/lhcddpj4/pv-s%C3%A9ance-du-cc-10122025.pdf", "2025-12-10"),
        ("", "https://www.locarno.ch/files/documenti/2026_05_18_verbale_albo.pdf", "2026-05-18"),
        ("Seduta ordinaria del 15-16 giugno 2026", "x", "2026-06-16"),
        ("Sitzplan 2026-2029", "x", None),
    ],
)
def test_parse_dates(text, url, expected):
    got = parse_date_with_url(text, url, None, "dmy")
    assert (got.isoformat() if got else None) == expected


def test_custom_date_regex_ymd():
    assert (
        parse_date("Sitzung 2025-03-18", r"(\d{4})-(\d{2})-(\d{2})", "ymd").isoformat()
        == "2025-03-18"
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "/wp-content/uploads/2025/10/20260519_PV.pdf",
            "2026-05-19",
        ),  # yyyymmdd wins over the upload folder
        ("GV20240611.pdf", "2024-06-11"),
        ("Protokoll_05122023.pdf", "2023-12-05"),  # ddmmyyyy still works
        ("Sitzung 3.7.2025", "2025-07-03"),
    ],
)
def test_compact_and_bounded_dates(text, expected):
    assert parse_date(text).isoformat() == expected


def test_encoded_space_before_a_date_in_the_url_is_not_read_as_a_year():
    url = "https://www.example.ch/files/Protokoll%20GV%2011.06.2026.pdf"
    assert parse_date_with_url("Protokoll", url, None, "dmy").isoformat() == "2026-06-11"


def test_viewer_urls_are_unwrapped():
    wrapped = "https://www.example.ch/tools/pdf-viewer/web/viewer.php?file=https://www.example.ch/docs/pv-36.pdf"
    assert unwrap_viewer(wrapped) == "https://www.example.ch/docs/pv-36.pdf"
    assert (
        unwrap_viewer("https://www.example.ch/docs/pv-36.pdf?fp=1")
        == "https://www.example.ch/docs/pv-36.pdf?fp=1"
    )
    assert (
        unwrap_viewer("https://www.example.ch/page?file=notapdf")
        == "https://www.example.ch/page?file=notapdf"
    )


def test_exclude_regex_drops_matching_anchors():
    html = (FIX / "wettingen_year_page" / "input.html").read_text(errors="ignore")
    step = AdapterStep(
        selector="a[href*='/_doc/']",
        text_regex="Einwohnerratssitzung",
        exclude_regex=r"0[1-3]/2025",
    )
    out = HtmlLinksAdapter().extract_links(
        html, "https://www.wettingen.ch/polprotokolle/2415010", step, None, "dmy"
    )
    assert out and not any(re.search(r"0[1-3]/2025", link.text) for link in out)


def test_month_names_do_not_match_inside_words():
    assert parse_date("Gemeindeversammlungen 2019") is None  # "gen" is not gennaio
    assert parse_date("Marktplatz 2021") is None  # "mar" is not March
    assert parse_date("16. Jun. 2025").isoformat() == "2025-06-16"
    assert parse_date("Verbale del 15 gen 2024").isoformat() == "2024-01-15"


def test_url_date_ignores_content_addressed_file_names():
    """A 64-hex digest on a CDN can spell a date (here 20520204); it must not become one."""
    from opencommune.crawl.adapters.html_links import parse_date_with_url

    url = "https://cdn.example/public/media/ba0d66c91727465f0130d8adbe37fbe86504feb52dc3678a04f3c15c6bb66fe5-261283.pdf"
    assert parse_date_with_url("Comptes 2024", url, None, "dmy") is None
    assert parse_date_with_url("PV du 04.06.2025", url, None, "dmy") == dt.date(2025, 6, 4)
    assert parse_date_with_url("", "https://x.ch/files/PV_20251216.pdf", None, "dmy") == dt.date(
        2025, 12, 16
    )
