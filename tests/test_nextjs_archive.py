"""Public hydration discovery without JavaScript execution or widened host scope."""

import json

from opencommune.crawl.discovery import page_links
from opencommune.crawl.html_parse import parse_html
from opencommune.crawl.linked_archive import LinkedSource, documents
from opencommune.crawl.sites.nextjs import link_tags

HOST = "https://municipality.example"


def flight(value):
    return "<script>self.__next_f.push(" + json.dumps([1, value]) + ")</script>"


def test_split_flight_records_and_classic_next_data():
    row = (
        "a:"
        + json.dumps(
            {"navigation": [{"href": "/archive/older"}], "files": [{"publicUrl": "/budget.pdf"}]}
        )
        + "\n"
    )
    html = flight(row[:35]) + flight(row[35:])
    html += (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"href": "/accounts.pdf"}})
        + "</script>"
    )
    assert {a["href"] for a in link_tags(parse_html(html))} == {
        "/archive/older",
        "/budget.pdf",
        "/accounts.pdf",
    }


def test_untrusted_payload_cannot_expand_scope_or_run_code():
    row = (
        "2:"
        + json.dumps(
            {
                "href": "/archive/older",
                "files": [
                    {"publicUrl": "/budget.pdf"},
                    {"url": "https://other.example/private.pdf"},
                    {"src": "javascript:alert(1)"},
                    {"title": "https://municipality.example/not-a-link.pdf"},
                ],
            }
        )
        + "\n"
    )
    html = flight(row) + "<script>self.__next_f.push(executeSomething())</script>"
    source = LinkedSource(
        bfs_id=1,
        website=HOST,
        vendor="custom",
        listing_urls=[HOST + "/archive"],
        crawl_prefixes=[HOST + "/archive"],
    )
    found = documents(html, HOST + "/archive", source)
    assert found == {HOST + "/budget.pdf": HOST + "/archive"}
    assert page_links(html, HOST + "/archive", source, found) == [HOST + "/archive/older"]


def test_malformed_and_non_data_scripts_are_ignored():
    html = '<script src="app.js">self.__next_f.push([1,"1:{\\"href\\":\\"/bad.pdf\\"}"])</script>'
    html += flight('1:I["module"]\n2:T5,hello\n3:{broken}\n')
    html += '<script>self.__next_f.push([1,"1:{}"] + invoke())</script>'
    assert link_tags(parse_html(html)) == []
