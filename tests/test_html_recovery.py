from pathlib import Path

from bs4 import BeautifulSoup

from opencommune.crawl.discovery import page_links
from opencommune.crawl.html_parse import parse_html
from opencommune.crawl.linked_archive import LinkedSource, documents


def test_malformed_cdata_page_keeps_documents_and_navigation():
    # Recorded official Ruedtligen-Alchenflueh homepage, 2026-09-26.
    html = (Path(__file__).parent / "fixtures/html_recovery/weblication_cdata.html").read_text()
    assert not BeautifulSoup(html, "html.parser").select("a[href]")
    recovered = parse_html(html)
    assert len(recovered.select("a[href]")) == 144
    listing = "https://www.ruedtligen-alchenflueh.ch/"
    source = LinkedSource(
        bfs_id=420,
        website=listing,
        vendor="custom",
        listing_urls=[listing],
        crawl_prefixes=[listing + "de/verwaltung/"],
    )
    pdfs = documents(html, listing, source)
    assert pdfs and all("/wAssets/docs/" in u for u in pdfs)
    children = page_links(html, listing, source, pdfs)
    assert any(u.startswith(listing + "de/verwaltung/") for u in children)
    assert all(u == listing or u.startswith(listing + "de/verwaltung/") for u in children)


def test_normal_markup_preserves_base_and_does_not_parse_script_strings_as_links():
    html = '<base href="https://example.test/docs/"><a href="budget.pdf">Budget</a>'
    soup = parse_html(html)
    assert soup.base["href"] == "https://example.test/docs/"
    assert soup.a["href"] == "budget.pdf"
    assert not parse_html("<script>const example = '<a href=\"fake.pdf\">';</script>").find("a")


def test_partial_cdata_loss_recovers_later_links_after_early_anchor():
    html = (Path(__file__).parent / "fixtures/html_recovery/weblication_cdata.html").read_text()
    html = '<a href="/early">Navigation</a>' + html
    assert len(BeautifulSoup(html, "html.parser").select("a[href]")) == 1
    recovered = parse_html(html)
    assert len(recovered.select("a[href]")) == 145
    assert recovered.select_one('a[href="/early"]') is not None


def test_script_template_anchor_does_not_trigger_false_recovery():
    html = "<script>const template = '<a href=\"fake.pdf\">Fake</a>';</script>"
    assert parse_html(html).select("a[href]") == []
