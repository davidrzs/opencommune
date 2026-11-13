"""Schaffhausen cantonal CMS adapter on synthetic nodes; recorded nodes live in tests/fixtures/sh_cms."""

import datetime as dt
import json

import pytest

from opencommune.crawl.adapters.sh_cms import ShCmsAdapter, _group_date, node_url
from opencommune.schemas import AdapterConfig, AdapterStep, SourceConfig

ADAPTER = ShCmsAdapter()
BASE = "https://www.example.ch/CMS/content?contentid=4040278&language=DE"


def _article(groups: list[dict]) -> str:
    tree = [
        {"type": "section", "cols": [{"fields": [{"type": "contentButtonAdder", "data": g}]}]}
        for g in groups
    ]
    return json.dumps(
        {"contentid": "4040278", "contenttypeid": "499", "data_widget_data": json.dumps(tree)}
    )


def _file(
    cid: str, name: str, listlabel: str | None = None, filetype: str = "pdf", pub: str = ""
) -> str:
    return json.dumps(
        {
            "contentid": cid,
            "contenttypeid": "101",
            "data_filetype": filetype,
            "data_listlabel": listlabel,
            "data_publication_date": pub,
            "data_filemeta": json.dumps({"url": f"/CMS/get/file/{cid}-uuid", "originalname": name}),
        }
    )


def test_listing_urls_accept_page_and_node_urls():
    src = SourceConfig(
        adapter="sh_cms",
        listing_urls=[
            "https://www.hallau.ch/CMS/Webseite/Gemeinde-Hallau/Gemeindeversammlung-4040278-DE.html",
            "https://www.hallau.ch/CMS/content?contentid=4040278&language=DE",
        ],
        adapter_config=AdapterConfig(steps=[AdapterStep(selector="buttons")]),
    )
    assert (
        ADAPTER.listing_urls(src)
        == ["https://www.hallau.ch/CMS/content?contentid=4040278&language=DE"] * 2
    )
    with pytest.raises(ValueError):
        node_url("https://www.hallau.ch/")


def test_group_date_joins_a_leading_year_with_day_and_month():
    assert _group_date("2. GV 2026 vom 16. Juni 2026", None, "dmy") == dt.date(2026, 6, 16)
    assert _group_date("1. GV 2023 vom 13. April", None, "dmy") == dt.date(2023, 4, 13)
    assert _group_date("Protokolle", None, "dmy") is None


def test_buttons_step_uses_labels_and_group_dates_and_filters():
    article = _article(
        [
            {
                "title": "2. GV 2026 vom 16. Juni 2026",
                "buttons": [
                    {"contentid": "1", "contenttypeid": "101"},
                    {"contentid": "2", "contenttypeid": "101"},
                    {"contentid": "3", "contenttypeid": "403"},  # an event, not a file
                ],
                "customLabels": [
                    {"contentid": "1", "label": "0 Einladung"},
                    {"contentid": "2", "label": "6 Protokoll"},
                ],
            },
            {  # stale buttons, live ids only in the labels (Rüdlingen)
                "title": "Protokolle",
                "buttons": [{"contentid": "9", "contenttypeid": "101"}],
                "customLabels": [
                    {"contentid": "7", "label": "Protokoll GV Nr. 116, 27. Nov. 2020"}
                ],
            },
        ]
    )
    links = ADAPTER.extract_links(
        article, BASE, AdapterStep(selector="buttons", text_regex="Protokoll"), None, "dmy"
    )
    assert [(x.text, x.date, x.upstream_id) for x in links] == [
        ("6 Protokoll (2. GV 2026 vom 16. Juni 2026)", dt.date(2026, 6, 16), "2"),
        ("Protokoll GV Nr. 116, 27. Nov. 2020 (Protokolle)", dt.date(2020, 11, 27), "7"),
        ("Protokolle", None, "9"),
    ]
    assert links[0].url == "https://www.example.ch/CMS/content?contentid=2&language=DE"
    assert links[0].context_date == dt.date(2026, 6, 16) and links[1].context_date is None


def test_file_step_reads_the_pdf_and_falls_back_to_the_parent_date():
    parent = ADAPTER.extract_links(
        _article(
            [
                {
                    "title": "1. GV 2025 vom 5. Juni",
                    "buttons": [{"contentid": "5", "contenttypeid": "101"}],
                    "customLabels": [{"contentid": "5", "label": "Protokoll"}],
                }
            ]
        ),
        BASE,
        AdapterStep(selector="buttons"),
        None,
        "dmy",
    )[0]
    step = AdapterStep(selector="file", text_regex="Protokoll", kind="minutes")
    dated = ADAPTER.extract_links(
        _file("5", "x.pdf", "Protokoll Gemeindeversammlung 05.06.2025"),
        parent.url,
        step,
        None,
        "dmy",
        parent=parent,
    )
    assert [(x.text, x.date, x.context_date, x.url) for x in dated] == [
        (
            "Protokoll Gemeindeversammlung 05.06.2025",
            dt.date(2025, 6, 5),
            None,
            "https://www.example.ch/CMS/get/file/5-uuid",
        )
    ]
    undated = ADAPTER.extract_links(
        _file("5", "Protokoll.pdf", None), parent.url, step, None, "dmy", parent=parent
    )
    assert undated[0].date == dt.date(2025, 6, 5) and undated[0].context_date == dt.date(2025, 6, 5)
    published = ADAPTER.extract_links(
        _file("5", "Protokoll.pdf", None, pub="30.06.2025"), parent.url, step, None, "dmy"
    )
    assert published[0].date == dt.date(2025, 6, 30)
    assert (
        ADAPTER.extract_links(
            _file("5", "Protokoll.docx", None, filetype="docx"), parent.url, step, None, "dmy"
        )
        == []
    )
    assert (
        ADAPTER.extract_links(
            _file("5", "Budget.pdf", "Budget 2026"), parent.url, step, None, "dmy"
        )
        == []
    )
    assert (
        ADAPTER.extract_links(
            json.dumps({"contentid": "9", "contenttypeid": "0"}), parent.url, step, None, "dmy"
        )
        == []
    )


def test_kiosk_list_urls_pass_through_and_ask_for_html():
    kiosk = "https://thayngen.ch/CMS/lists/list?filter_customposttypeid_int=101&rows=200"
    source = SourceConfig(
        adapter="sh_cms",
        listing_urls=[kiosk, "https://thayngen.ch/CMS/Webseite/x/Protokolle-2289981-DE.html"],
        adapter_config=AdapterConfig(steps=[AdapterStep(selector="kiosk")]),
    )
    assert ADAPTER.listing_urls(source) == [
        kiosk,
        "https://thayngen.ch/CMS/content?contentid=2289981&language=DE",
    ]
    step = AdapterStep(selector="kiosk")
    assert "accept" not in ADAPTER.request(step, kiosk).headers
    assert ADAPTER.request(step, BASE).headers["accept"] == "application/json"


def test_kiosk_step_unescapes_names_and_ignores_the_publication_date():
    meta = '{\\"url\\":\\"/CMS/get/file/abc\\",\\"originalname\\":\\"Protokoll vom 12. M\\u00e4rz 2026.pdf\\"}'
    html = (
        '<div class="list_item_anchor"><a contentid="7"><script>'
        f"let fileMeta = JSON.parse('{meta}');"
        "var title = PS.Helper.replaceBR('Protokoll der Sitzung des Einwohnerrats');"
        "var publicationDate = '04.06.2026';</script></a></div>"
    )
    (link,) = ADAPTER.extract_links(html, BASE, AdapterStep(selector="kiosk"), None, "dmy")
    assert link.url == "https://www.example.ch/CMS/get/file/abc"
    assert link.date == dt.date(2026, 3, 12) and link.upstream_id == "7"
    undated = html.replace("vom 12. M\\u00e4rz 2026", "2026")
    (link,) = ADAPTER.extract_links(undated, BASE, AdapterStep(selector="kiosk"), None, "dmy")
    assert link.date is None
