import json

from opencommune.crawl.html_parse import parse_html
from opencommune.crawl.linked_archive import LinkedSource, documents
from opencommune.crawl.sites.wix import document_urls


def page(nodes):
    return (
        '<script id="wix-warmup-data" type="application/json">'
        + json.dumps({"platform": {"content": {"nodes": nodes}}})
        + "</script>"
    )


def file_node(file_id="ugd/abcdef_123456.pdf", private=False):
    return {"type": "FILE", "fileData": {"type": "pdf", "src": {"id": file_id, "private": private}}}


def test_public_rich_content_files_keep_municipal_tenant_scope():
    html = page([file_node(), file_node(), file_node("ugd/fedcba_123456.pdf")])
    listing = "https://municipality.test/news"
    source = LinkedSource(
        bfs_id=1,
        website="https://municipality.test",
        vendor="wix",
        listing_urls=[listing],
        wix_file_owner="abcdef",
        attribution_note="Municipal tenant observed on the official page.",
    )
    assert documents(html, listing, source) == {
        "https://static.wixstatic.com/ugd/abcdef_123456.pdf": listing
    }


def test_private_unknown_and_unsafe_files_are_excluded():
    nodes = [
        file_node(private=True),
        file_node(private=None),
        file_node("../private.pdf"),
        file_node("https://elsewhere.test/a.pdf"),
        file_node("ugd/abc_def.pdf?token=x"),
    ]
    nodes.append({"type": "TEXT", "fileData": file_node()["fileData"]})
    assert document_urls(parse_html(page(nodes))) == []
    assert (
        document_urls(
            parse_html('<script id="wix-warmup-data" type="application/json">bad</script>')
        )
        == []
    )


def test_public_odoo_share_download_route():
    listing = "https://municipality.test/document/share/1/12345678-1234-1234-1234-123456789abc"
    url = listing.replace("/share/", "/download/") + "/42"
    source = LinkedSource(
        bfs_id=1, website="https://municipality.test", vendor="custom", listing_urls=[listing]
    )
    html = f'<a href="{url}">Download file</a><a href="{url}?preview=True">Preview</a><a href="/document/download/admin">Other</a>'
    assert documents(html, listing, source) == {url: listing}
