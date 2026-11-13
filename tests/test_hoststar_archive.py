"""Hoststar widget extraction uses only the embedded JSON, never JavaScript execution."""

import json

from opencommune.crawl.sites.hoststar import extract_pdf_urls


def page(components):
    return f"<script>Server.components = {json.dumps(components)}; Server.ready();</script>"


def test_extracts_only_public_pdf_filedownload_widgets_in_order():
    html = page(
        {
            "first": {
                "type": "widget.filedownload",
                "data": {"url": "http://files.designer.hoststar.ch/2e/91/first.pdf"},
            },
            "image": {"type": "widget.image", "data": {"url": "https://bad.test/image.pdf"}},
            "relative": {
                "type": "widget.filedownload",
                "data": {"url": "/local/second.PDF?download=1"},
            },
            "duplicate": {
                "type": "widget.filedownload",
                "data": {"url": "http://files.designer.hoststar.ch/2e/91/first.pdf"},
            },
            "private": {
                "type": "widget.filedownload",
                "data": {"url": "https://u:p@bad.test/x.pdf"},
            },
            "other": {"type": "widget.filedownload", "data": {"url": "https://bad.test/x.docx"}},
        }
    )
    assert extract_pdf_urls(html, "https://municipality.test/reglemente") == [
        "http://files.designer.hoststar.ch/2e/91/first.pdf",
        "https://municipality.test/local/second.PDF?download=1",
    ]


def test_malformed_component_data_is_ignored():
    html = "<script>Server.components = {bad json};</script>" + page(
        {"broken": {"type": "widget.filedownload", "data": []}}
    )
    assert extract_pdf_urls(html, "https://municipality.test/") == []
