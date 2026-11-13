"""WordPress media REST adapter on synthetic responses; recorded responses live in tests/fixtures/wp_media."""

import datetime as dt
import json

from opencommune.crawl.adapters.wp_media import WpMediaAdapter
from opencommune.schemas import AdapterConfig, AdapterStep, SourceConfig

ADAPTER = WpMediaAdapter()
STEP = AdapterStep(selector="media")
ENDPOINT = "https://www.example.ch/wp-json/wp/v2/media"


def _source(*urls: str) -> SourceConfig:
    return SourceConfig(
        adapter="wp_media", listing_urls=list(urls), adapter_config=AdapterConfig(steps=[STEP])
    )


def _item(id_: int, title: str, file: str, mime: str = "application/pdf") -> dict:
    return {
        "id": id_,
        "date": "2026-03-23T15:19:24",
        "title": {"rendered": title},
        "mime_type": mime,
        "source_url": f"https://www.example.ch/wp-content/uploads/2026/03/{file}",
    }


def test_listing_urls_fill_in_mime_filter_page_size_and_page():
    urls = ADAPTER.listing_urls(
        _source("https://www.example.ch", ENDPOINT + "?search=protokoll&per_page=20")
    )
    assert urls[0] == ENDPOINT + "?mime_type=application%2Fpdf&per_page=100&page=1"
    assert urls[1] == ENDPOINT + "?search=protokoll&per_page=20&mime_type=application%2Fpdf&page=1"


def test_request_asks_for_json():
    req = ADAPTER.request(STEP, ENDPOINT + "?page=1")
    assert req.method == "GET" and req.headers["Accept"] == "application/json"


def test_links_from_title_or_file_name_dates_and_filters():
    items = [
        _item(
            1,
            "Protokoll der Urversammlung vom 26. November 2025u",
            "Protokoll-der-Urversammlung-vom-26.-November-2025u.pdf",
        ),
        _item(2, "Protokoll GV", "Protokoll-GV-vom-9.4.26.pdf"),
        _item(3, "Protokoll Urversammlung Juni 2024", "Protokoll-Urversammlung-Juni-2024.pdf"),
        _item(4, "formular-4-protokoll", "formular-4-protokoll-6.pdf"),
        _item(
            5,
            "Protokoll der Urversammlung vom 04. Juni 2025",
            "Protokoll-der-Urversammlung-vom-04.-Juni-2025.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        _item(6, "Protokoll &#8211; Sitzung", "x.pdf"),
    ]
    out = ADAPTER.extract_links(
        json.dumps(items),
        ENDPOINT,
        AdapterStep(selector="media", text_regex="^Protokoll", exclude_regex="Sitzung"),
        None,
        "dmy",
    )
    assert [link.upstream_id for link in out] == [
        "1",
        "2",
        "3",
    ]  # the docx twin, the form and the excluded title are gone
    assert [link.date for link in out] == [
        dt.date(2025, 11, 26),
        dt.date(2026, 4, 9),
        dt.date(2024, 6, 1),
    ]
    assert [link.date_precision for link in out] == ["day", "day", "month"]
    assert out[0].text == "Protokoll der Urversammlung vom 26. November 2025u"


def test_upload_folder_year_is_not_used_for_the_meeting_date():
    (link,) = ADAPTER.extract_links(
        json.dumps([_item(1, "Protokoll vom 26. November", "Protokoll-vom-26.-November.pdf")]),
        ENDPOINT,
        STEP,
        None,
        "dmy",
    )
    assert link.date is None


def test_error_objects_and_bad_json_yield_nothing():
    assert (
        ADAPTER.extract_links(
            '{"code": "rest_post_invalid_page_number"}', ENDPOINT, STEP, None, "dmy"
        )
        == []
    )
    assert ADAPTER.extract_links("<html>", ENDPOINT, STEP, None, "dmy") == []


def test_next_url_follows_x_wp_totalpages_when_headers_are_given():
    url = ENDPOINT + "?search=protokoll&per_page=100&page=1"
    assert (
        ADAPTER.next_url("[]", url, STEP, headers={"X-WP-Total": "230", "X-WP-TotalPages": "3"})
        == ENDPOINT + "?search=protokoll&per_page=100&page=2"
    )
    assert (
        ADAPTER.next_url(
            "[]", url.replace("page=1", "page=3"), STEP, headers={"x-wp-totalpages": "3"}
        )
        is None
    )


def test_next_url_without_headers_continues_while_a_page_is_full():
    url = ENDPOINT + "?per_page=2&page=1"
    full = json.dumps([_item(1, "a", "a.pdf"), _item(2, "b", "b.pdf")])
    assert ADAPTER.next_url(full, url, STEP) == ENDPOINT + "?per_page=2&page=2"
    assert ADAPTER.next_url(json.dumps([_item(1, "a", "a.pdf")]), url, STEP) is None
    assert ADAPTER.next_url('{"code": "rest_post_invalid_page_number"}', url, STEP) is None
