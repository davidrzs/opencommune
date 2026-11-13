"""Broad discovery must preserve all statuses, linked provenance and request boundaries."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    spec = importlib.util.spec_from_file_location(
        "probe_listings", Path(__file__).resolve().parents[1] / "scripts" / "probe_listings.py"
    )
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
finally:
    sys.path.pop(0)


@pytest.mark.parametrize("status", [200, 206])
def test_pdf_prefix_is_bounded_even_when_server_ignores_range(monkeypatch, status):
    class Stream(httpx.SyncByteStream):
        consumed = 0
        closed = False

        def __iter__(self):
            for index in range(100):
                self.consumed += 1
                yield b"%PDF-" + b"x" * 1019 if index == 0 else b"x" * 1024

        def close(self):
            self.closed = True

    stream = Stream()

    def send(client, polite, request, **kwargs):
        assert kwargs == {"stream": True}
        assert request.headers["range"] == "bytes=0-1023"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(status, stream=stream, request=request)

    monkeypatch.setattr(probe.http, "_send", send)
    with httpx.Client() as client:
        meta, body = probe.request(
            "https://commune.test/file.pdf",
            client,
            SimpleNamespace(allowed=lambda _: True),
            prefix=True,
        )
    assert meta["status"] == "ok" and len(body) == 1024 and body.startswith(b"%PDF-")
    assert stream.consumed == 1 and stream.closed


def test_pdf_prefix_rejects_compressed_response_without_reading_it(monkeypatch):
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("Encoded document must not be consumed")
            yield b""

    monkeypatch.setattr(
        probe.http,
        "_send",
        lambda client, polite, request, **kwargs: httpx.Response(
            200, headers={"content-encoding": "gzip"}, stream=Stream(), request=request
        ),
    )
    with httpx.Client() as client:
        meta, body = probe.request(
            "https://commune.test/file.pdf",
            client,
            SimpleNamespace(allowed=lambda _: True),
            prefix=True,
        )
    assert meta["status"] == "unsupported_encoding" and body == b""


def test_broad_links_include_undated_pdfs_and_keep_external_for_review():
    docs, pages = probe.links(
        """
      <a href="/fileadmin/budget.PDF?download=1">Budget</a>
      <a href="https://files.example.org/report.pdf">Rapport</a>
      <a href="/verwaltung/downloads">Downloads</a>
      <a href="/politik/gemeindeversammlung">Gemeindeversammlung</a>
      <a href="https://outside.test/documents">Documents</a>
      <a href="javascript:alert(1)">Documents</a>
    """,
        "https://commune.test/",
        "https://commune.test/",
    )
    assert len(docs) == 2
    assert docs[0]["same_site"] is True
    assert docs[1]["same_site"] is False
    assert all(d["listing_url"] == "https://commune.test/" for d in docs)
    assert pages == [
        "https://commune.test/verwaltung/downloads",
        "https://commune.test/politik/gemeindeversammlung",
    ]


def test_sitemaps_follow_only_same_site_and_preserve_signed_queries():
    indexes, pages = probe.sitemap_links(
        b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://commune.test/sitemap.xml?type=1&amp;cHash=abc</loc></sitemap>
      <sitemap><loc>https://outside.test/sitemap.xml</loc></sitemap>
    </sitemapindex>""",
        "https://commune.test",
    )
    assert indexes == ["https://commune.test/sitemap.xml?type=1&cHash=abc"]
    assert pages == []


def test_review_earlier_negative_and_verify_signature(tmp_path, monkeypatch):
    (tmp_path / "pages").mkdir()
    entry = SimpleNamespace(
        bfs_id=1,
        name="Example",
        canton="BE",
        status="not_published",
        website="https://commune.test/",
        publications=[],
    )
    calls = []

    def request(url, *args, **kwargs):
        calls.append(url)
        if kwargs.get("prefix"):
            return {"url": url, "status": "ok", "http_status": 200}, b"%PDF-1.7\n"
        if url.endswith("sitemap.xml"):
            return {"url": url, "status": "http_error", "http_status": 404}, b""
        return {
            "url": url,
            "status": "ok",
            "content_type": "text/html",
        }, b'<a href="/budget.pdf">Budget</a>'

    monkeypatch.setattr(probe, "safe_request", request)
    result = probe.probe(entry, None, SimpleNamespace(), tmp_path, 3)
    assert result["original_status"] == "not_published"
    assert result["status"] == "verified_pdf"
    assert result["documents"][0]["listing_url"] == entry.website
    assert calls[-1] == "https://commune.test/budget.pdf"


def test_throttle_stops_site_before_more_pages_or_pdf_checks(tmp_path, monkeypatch):
    (tmp_path / "pages").mkdir()
    entry = SimpleNamespace(
        bfs_id=1,
        name="Example",
        canton="BE",
        status="configured",
        website="https://commune.test/",
        publications=[],
    )
    calls = []

    def request(url, *args, **kwargs):
        calls.append(url)
        return {"url": url, "status": "http_error", "http_status": 429}, b""

    monkeypatch.setattr(probe, "safe_request", request)
    result = probe.probe(entry, None, SimpleNamespace(), tmp_path, 8)
    assert calls == [entry.website]
    assert result["pdf_checks"] == []


def test_declared_html_base_resolves_files_without_changing_listing_provenance():
    docs, pages = probe.links(
        '<base href="https://commune.test/"><a href="fileadmin/budget.pdf">Budget</a>'
        '<a href="verwaltung/downloads">Documents</a>',
        "https://commune.test/verwaltung/gemeindeversammlung/",
        "https://commune.test/",
    )
    assert docs[0]["url"] == "https://commune.test/fileadmin/budget.pdf"
    assert docs[0]["listing_url"] == "https://commune.test/verwaltung/gemeindeversammlung/"
    assert pages == ["https://commune.test/verwaltung/downloads"]


@pytest.mark.parametrize("vendor", ["typo3", "drupal", "govis", "custom", "unknown"])
@pytest.mark.parametrize("subset", [False, True])
def test_main_includes_every_status_for_selected_vendor(tmp_path, monkeypatch, vendor, subset):
    import json

    entries = [
        SimpleNamespace(bfs_id=i, name=str(i), vendor=vendor, status=status, website=None)
        for i, status in enumerate(
            ("configured", "candidate", "not_examined", "not_published", "needs_feature"), 1
        )
    ]
    entries.append(SimpleNamespace(bfs_id=6, vendor="wordpress"))
    if vendor == "unknown":
        entries[0].vendor = None
    monkeypatch.setattr(probe, "load_register", lambda: entries)
    monkeypatch.setattr(probe.settings, "data_dir", tmp_path)
    argv = ["probe_listings.py", "--vendor", vendor]
    if subset:
        selection = tmp_path / "targets.json"
        selection.write_text(json.dumps([2, 3]))
        argv += ["--commune-file", str(selection)]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(probe.http, "ATTEMPTS", probe.http.ATTEMPTS)
    monkeypatch.setattr(
        probe,
        "probe",
        lambda e, *args: {
            "bfs_id": e.bfs_id,
            "name": e.name,
            "original_status": e.status,
            "status": "missing_website",
        },
    )
    probe.main()
    results = json.loads((tmp_path / "discovery" / vendor / "probe.json").read_text())
    assert set(results) == ({"2", "3"} if subset else {"1", "2", "3", "4", "5"})


def test_portal_and_online_counter_navigation():
    _, pages = probe.links(
        '<a href="de/willkommen/">Gemischte Gemeinde</a>'
        '<a href="/de/verwaltung/onlineschalter/">Online-Schalter</a>',
        "https://commune.test/",
        "https://commune.test/",
    )
    assert set(pages) == {
        "https://commune.test/de/willkommen/",
        "https://commune.test/de/verwaltung/onlineschalter/",
    }


def test_xhtml_xml_declaration_does_not_turn_html_into_a_sitemap(tmp_path, monkeypatch):
    (tmp_path / "pages").mkdir()
    entry = SimpleNamespace(
        bfs_id=1,
        name="Example",
        canton="FR",
        status="configured",
        website="https://commune.test/",
        publications=[],
    )

    def request(url, *args, **kwargs):
        if kwargs.get("prefix"):
            return {"url": url, "status": "ok"}, b"%PDF-1.7"
        return {
            "url": url,
            "status": "ok",
            "content_type": "text/html",
        }, b'<?xml version="1.0"?><html><body><a href="/report.pdf">Rapport</a></body></html>'

    monkeypatch.setattr(probe, "safe_request", request)
    row = probe.probe(entry, None, SimpleNamespace(), tmp_path, 3)
    assert row["status"] == "verified_pdf"
    assert row["documents"][0]["url"] == "https://commune.test/report.pdf"


def test_retry_incomplete_preserves_successes_and_throttled_sites():
    e = SimpleNamespace(bfs_id=1)
    assert probe.eligible(e, {}, False)
    for status, code, retry, expected in [
        ("verified_pdf", 200, True, False),
        ("no_pdf_found", 200, False, False),
        ("no_pdf_found", 200, True, True),
        ("unreachable_or_blocked", 429, True, False),
    ]:
        previous = {"status": status, "pages": [{"http_status": code}], "pdf_checks": []}
        assert probe.eligible(e, {"1": previous}, retry) is expected


def test_registered_listing_children_precede_unrelated_home_navigation(tmp_path, monkeypatch):
    (tmp_path / "pages").mkdir()
    entry = SimpleNamespace(
        bfs_id=1,
        name="Example",
        canton="GE",
        status="configured",
        website="https://commune.test/",
        publications=[SimpleNamespace(listing_url="https://commune.test/publications?page={0..6}")],
    )
    calls = []

    def request(url, *args, **kwargs):
        calls.append(url)
        if kwargs.get("prefix"):
            return {"url": url, "status": "ok"}, b"%PDF-1.7"
        if url == entry.website:
            body = "".join(
                f'<a href="/actualites/news-{i}">Actualites</a>' for i in range(20)
            ).encode()
        elif url == "https://commune.test/publications?page=0":
            body = b'<a href="/publications/proces-verbal-2026">Proces verbal</a>'
        elif url.endswith("proces-verbal-2026"):
            body = b'<a href="/minutes.pdf">PDF</a>'
        else:
            body = b""
        return {"url": url, "status": "ok", "content_type": "text/html"}, body

    monkeypatch.setattr(probe, "safe_request", request)
    result = probe.probe(entry, None, SimpleNamespace(), tmp_path, 3)
    assert result["status"] == "verified_pdf"
    assert calls[:3] == [
        entry.website,
        "https://commune.test/publications?page=0",
        "https://commune.test/publications/proces-verbal-2026",
    ]


def test_platform_hints_use_markup_not_page_prose():
    assert probe.platform_hints("<p>We read about WordPress and Assolo</p>") == []
    assert probe.platform_hints(
        "<meta name='generator' content='Contao CMS'><script src='/wp-content/a.js'></script><a href='https://www.assolo.net'>Provider</a>"
    ) == ["assolo", "generator:Contao CMS", "wordpress"]


def test_shared_ticino_asset_family_is_a_hint_without_vendor_attribution():
    assert probe.platform_hints('<script src="/AAjax/AAjax.js"></script>') == ["aajax-assets"]


def test_opaque_document_anchors_are_candidates_not_navigation():
    docs, _ = probe.links(
        '<a class="ListDocLink" href="/Decisioni-1234abcd?i=1">Decisioni</a>'
        '<a class="ObjListDocLink" href="/Regolamento-2345bcde">Regolamento</a>'
        '<a href="/Comune-abcdef12">Comune</a>',
        "https://commune.test/",
        "https://commune.test/",
    )
    assert len(docs) == 2


@pytest.mark.parametrize(
    "payload,expected", [(b"%PDF-1.7\n", True), (b"<html>error</html>", False)]
)
def test_document_response_on_page_walk_checks_signature(monkeypatch, payload, expected):
    import httpx

    response = httpx.Response(
        200,
        content=payload,
        headers={"content-type": "application/pdf"},
        request=httpx.Request("GET", "https://commune.test/opaque"),
    )
    monkeypatch.setattr(probe.http, "_send", lambda *args, **kwargs: response)
    with httpx.Client() as client:
        meta, body = probe.request(
            "https://commune.test/opaque", client, SimpleNamespace(allowed=lambda url: True)
        )
    assert meta["status"] == "pdf_document"
    assert meta["pdf_signature"] is expected
    assert body == b""


def test_pdf_found_as_page_is_kept_without_duplicate_probe(tmp_path, monkeypatch):
    (tmp_path / "pages").mkdir()
    entry = SimpleNamespace(
        bfs_id=1,
        name="Example",
        canton="TI",
        status="candidate",
        website="https://commune.test/",
        publications=[],
    )
    calls = []

    def request(url, *args, **kwargs):
        calls.append(url)
        if url.endswith("/Verbali-1234abcd"):
            return {
                "url": url,
                "status": "pdf_document",
                "pdf_signature": True,
                "http_status": 200,
                "content_type": "application/pdf",
            }, b""
        if url.endswith("sitemap.xml"):
            return {"url": url, "status": "http_error", "http_status": 404}, b""
        return {"url": url, "status": "ok"}, b'<a href="/Verbali-1234abcd">Verbali</a>'

    monkeypatch.setattr(probe, "safe_request", request)
    row = probe.probe(entry, None, SimpleNamespace(), tmp_path, 4)
    assert row["status"] == "verified_pdf"
    assert row["documents"][0]["url"].endswith("/Verbali-1234abcd")
    assert calls.count("https://commune.test/Verbali-1234abcd") == 1


def test_italian_archive_navigation_is_followed_and_prioritised():
    paths = [
        "regolamenti",
        "ordinanze",
        "risoluzioni",
        "messaggi-municipali",
        "preventivi",
        "consuntivi",
        "moduli",
        "albo-comunale",
    ]
    html = "".join(f'<a href="/{path}">{path}</a>' for path in paths)
    docs, pages = probe.links(html, "https://commune.test/", "https://commune.test/")
    assert docs == []
    assert pages == [f"https://commune.test/{path}" for path in paths]
    assert all(probe.PRIORITY.search(path) for path in paths)


def test_municipal_portal_entry_is_followed():
    _, pages = probe.links(
        '<a href="/gemeinde/">Zur Website</a>', "https://commune.test/", "https://commune.test/"
    )
    assert pages == ["https://commune.test/gemeinde/"]


def test_regulations_take_precedence_over_online_form_navigation(tmp_path, monkeypatch):
    (tmp_path / "pages").mkdir()
    entry = SimpleNamespace(
        bfs_id=1,
        name="Example",
        canton="VS",
        status="not_examined",
        website="https://commune.test/",
        publications=[],
    )
    calls = []

    def request(url, *args, **kwargs):
        calls.append(url)
        html = (
            '<a href="/online-schalter/first">Form</a><a href="/reglemente">Reglemente</a>'
            if url == entry.website
            else ""
        )
        return {"url": url, "status": "ok", "content_type": "text/html"}, html.encode()

    monkeypatch.setattr(probe, "safe_request", request)
    probe.probe(entry, None, SimpleNamespace(), tmp_path, 2)
    assert calls == [entry.website, "https://commune.test/reglemente"]


def test_probe_reuses_embedded_pdf_and_hydration_readers():
    html = """<iframe src="/viewer?file=/files/budget.pdf"></iframe>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"links":[{"href":"/documents/archive"},
    {"publicUrl":"/files/accounts.pdf"},{"href":"https://outside.test/documents"}]}}
    </script>"""
    docs, pages = probe.links(html, "https://commune.test/", "https://commune.test/")
    assert {d["url"] for d in docs} == {
        "https://commune.test/files/budget.pdf",
        "https://commune.test/files/accounts.pdf",
    }
    assert pages == ["https://commune.test/documents/archive"]


def test_platform_hints_do_not_mislabel_site_from_external_documents():
    html = (
        '<script src="/typo3temp/main.js"></script><img src="/fileadmin/logo.png">'
        '<a href="https://other.test/wp-content/uploads/report.pdf">Other report</a>'
        '<a href="https://canton.test/sites/default/files/form.pdf">Canton</a>'
    )
    assert probe.platform_hints(html, "https://commune.test/") == ["typo3"]


def test_explicit_output_does_not_overwrite_original_survey(tmp_path, monkeypatch):
    import json

    original = tmp_path / "discovery" / "typo3" / "probe.json"
    original.parent.mkdir(parents=True)
    original.write_text('{"existing":"preserve"}')
    monkeypatch.setattr(probe.settings, "data_dir", tmp_path)
    entry = SimpleNamespace(
        bfs_id=1, name="Example", canton="BE", vendor="typo3", status="not_examined", website=None
    )
    monkeypatch.setattr(probe, "load_register", lambda: [entry])
    monkeypatch.setattr(probe.http, "ATTEMPTS", probe.http.ATTEMPTS)
    output = tmp_path / "review"
    monkeypatch.setattr(sys, "argv", ["probe_listings.py", "--output", str(output)])
    probe.main()
    assert json.loads((output / "probe.json").read_text())["1"]["status"] == "missing_website"
    assert original.read_text() == '{"existing":"preserve"}'
