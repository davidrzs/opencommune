"""Public PDF routes with an extension before a handler or in a query filename."""

import pytest
from bs4 import BeautifulSoup

from opencommune.crawl.adapters.html_links import is_pdf_candidate
from opencommune.crawl.linked_archive import LinkedSource, documents


@pytest.mark.parametrize(
    "url",
    [
        "https://city.test/finance/budget.pdf/download",
        "https://city.test/finance/BUDGET.PDF/download?inline=1",
        "https://city.test/appl/download.php?objid=935453958&id=205536290&nr=1&filename=Budget_2025.pdf&usid=7537&cmd=viewinline",
        "https://city.test/politik/cdws/dok.php?did=dea549d17373432886a435872a529f92-332&typ=pdf",
        "https://city.test/cdws/dok.php?did=123456&typ=pdf",
        "https://city.test/_iserv/dlfiles/dl.php?ddl=reglement-des-finances.pdf",
        "https://city.test/documents/dl/ce58b02d-3c61f1dd3a56-c0b789b2497d",
        "https://city.test/v2/index.php/download_file/force/3fd0914b-fb95-4563-a4a5-acdc06a5de51/259",
        "https://city.test/download_file/force/3fd0914b-fb95-4563-a4a5-acdc06a5de51/259",
        "https://city.test/download_file/force/2695/286",
        "https://city.test/FileDownload/Download/475",
        "https://city.test/l1/online-schalter-erlasse.php?dl=1&datei=Reglement.PDF",
    ],
)
def test_opaque_pdf_routes_are_candidates(url):
    anchor = BeautifulSoup(f'<a href="{url}">Document</a>', "html.parser").a
    assert is_pdf_candidate(anchor, url)


@pytest.mark.parametrize(
    "url",
    [
        "https://city.test/finance/budget.docx/download",
        "https://city.test/finance/budget.pdf/preview",
        "https://city.test/appl/download.php?objid=935453958&id=205536290&nr=1&filename=Budget_2025.docx&usid=7537&cmd=viewinline",
        "https://city.test/appl/download.php?objid=935453958&id=205536290&nr=1&filename=Budget_2025.pdf&usid=7537&cmd=delete",
        "https://city.test/appl/download.php?objid=other&id=205536290&nr=1&filename=Budget_2025.pdf&usid=7537&cmd=viewinline",
        "https://city.test/appl/download.php?objid=935453958&id=205536290&nr=1&filename=Budget_2025.pdf&filename=Other.pdf&usid=7537&cmd=viewinline",
        "https://city.test/politik/cdws/dok.php?did=dea549d17373432886a435872a529f92-332&typ=html",
        "https://city.test/politik/cdws/dok.php?did=other-332&typ=pdf",
        "https://city.test/politik/dok.php?did=123456&typ=pdf",
        "https://city.test/_iserv/dlfiles/dl.php?ddl=not-a-pdf.docx",
        "https://city.test/_iserv/dlfiles/dl.php?ddl=../other.pdf",
        "https://city.test/_iserv/dlfiles/dl.php?ddl=reglement.pdf&ddl=other.pdf",
        "https://city.test/documents/dl/not-a-document",
        "https://city.test/v2/index.php/download_file/force/3fd0914b-fb95-4563-a4a5-acdc06a5de51/not-numeric",
        "https://city.test/download_file/force/3fd0914b-fb95-4563-a4a5-acdc06a5de51/not-numeric",
        "https://city.test/download_file/force/2695/not-numeric",
        "https://city.test/download_file/force/not-an-id/286",
        "https://city.test/FileDownload/Download/not-numeric",
        "https://city.test/FileDownload/Preview/475",
        "https://city.test/FileDownload/Download/475/edit",
        "https://city.test/l1/library.php?dl=0&datei=Reglement.pdf",
        "https://city.test/l1/library.php?dl=1&datei=Reglement.docx",
        "https://city.test/l1/library.php?dl=1&datei=../Reglement.pdf",
        "https://city.test/l1/library.php?dl=1&datei=Reglement.pdf&datei=Other.pdf",
        "https://city.test/l1/library.php?dl=1&datei=Reglement.pdf&action=delete",
    ],
)
def test_unverified_opaque_routes_are_not_candidates(url):
    anchor = BeautifulSoup(f'<a href="{url}">Document</a>', "html.parser").a
    assert not is_pdf_candidate(anchor, url)


def test_filename_query_download_keeps_handler_and_municipal_scope():
    listing = "https://city.test/l1/online-schalter-erlasse.php"
    source = LinkedSource(
        bfs_id=1, website="https://city.test", vendor="custom", listing_urls=[listing]
    )
    html = """<a href="?dl=1&amp;datei=Reglement.pdf">Download</a>
      <a href="https://elsewhere.test/library.php?dl=1&amp;datei=Other.pdf">Download</a>
      <a href="?dl=1&amp;datei=Table.xlsx">Download</a>"""
    assert documents(html, listing, source) == {listing + "?dl=1&datei=Reglement.pdf": listing}


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        ('<a href="/item/123" download="annual-account.pdf">Download</a>', True),
        ('<a href="/item/123">Annual account 2025.PDF</a>', True),
        ('<a href="/item/123">Annual account.pdf <span> </span></a>', True),
        ('<a href="/item/123" download="annual-account.docx">Download</a>', False),
        ('<a href="/item/123">Annual account.pdf preview</a>', False),
        ('<a href="/item/123">Annual account.docx</a>', False),
    ],
)
def test_pdf_filename_hints_on_opaque_links(markup, expected):
    anchor = BeautifulSoup(markup, "html.parser").a
    assert is_pdf_candidate(anchor, "https://city.test/item/123") is expected


def test_plone_pdf_mime_icon_requires_the_published_download_anchor():
    html = (
        '<div><a href="/municipality/item/download"><span class="mimetype-icon '
        'icon-mimetype-mt-application-pdf"></span></a>'
        '<a href="/municipality/report/download">Other report</a>'
        '<a href="/municipality/document/download"><span class="mimetype-icon '
        'icon-mimetype-mt-application-msword"></span></a>'
        '<a href="/municipality/item"><span class="icon-mimetype-mt-application-pdf">'
        "</span></a></div>"
    )
    links = BeautifulSoup(html, "html.parser").select("a")
    assert [is_pdf_candidate(a, "https://portal.test" + a["href"]) for a in links] == [
        True,
        False,
        False,
        False,
    ]


def test_jdownloads_pdf_send_route_requires_document_markup():
    url = "https://city.test/index.php/divers/telechargements/send/39-reglements/222-rc-paz-leytron"
    link = BeautifulSoup(f'<a class="jd_download_url" href="{url}">Document</a>', "html.parser").a
    icon = BeautifulSoup(
        f'<a href="{url}"><img src="/images/jdownloads/fileimages/flat_1/pdf.png"></a>',
        "html.parser",
    ).a
    plain = BeautifulSoup(f'<a href="{url}">Navigation</a>', "html.parser").a
    assert is_pdf_candidate(link, url)
    assert is_pdf_candidate(icon, url)
    assert not is_pdf_candidate(plain, url)


def test_jdownloads_pdf_row_without_index_php():
    url = (
        "https://city.test/documenti-albo-comunale/messaggi-municipali/mm-2026/"
        "send/80-mm-2026/845-mm-2026-01-convenzione"
    )
    pdf_row = BeautifulSoup(
        f'<div><img src="/images/jdownloads/fileimages/pdf.png">'
        f'<div class="jd_download_url"><a href="{url}">Download</a></div></div>',
        "html.parser",
    ).a
    docx_row = BeautifulSoup(
        f'<div><img src="/images/jdownloads/fileimages/docx.png">'
        f'<div class="jd_download_url"><a href="{url}">Download</a></div></div>',
        "html.parser",
    ).a
    plain = BeautifulSoup(f'<a href="{url}">Navigation</a>', "html.parser").a
    assert is_pdf_candidate(pdf_row, url)
    assert not is_pdf_candidate(docx_row, url)
    assert not is_pdf_candidate(plain, url)


@pytest.mark.parametrize(
    "url",
    [
        "https://city.test/index.php/divers/telechargements/send/39-reglements/not-numeric",
        "https://city.test/index.php/divers/telechargements/send/39-reglements/222-rc-paz-leytron/delete",
        "https://city.test/divers/telechargements/send/39-reglements/222-rc-paz-leytron/delete",
    ],
)
def test_jdownloads_rejects_other_routes(url):
    anchor = BeautifulSoup(f'<a class="jd_download_url" href="{url}">Document</a>', "html.parser").a
    assert not is_pdf_candidate(anchor, url)


def test_phoca_pdf_icon_allows_mount_without_category_path():
    url = "https://www.cossonay.ch/documents/7-reglements/39-reglements-communaux?download=1694:emoluments-pour-guichet-virtuel"
    marked = BeautifulSoup(
        '<div class="pd-document16" style="background: url(\'https://www.cossonay.ch/media/com_phocadownload/images/mime/16/icon-pdf.png\') 0 center no-repeat">'
        f'<div class="pd-float"><a href="{url}">Emoluments pour guichet virtuel</a></div></div>',
        "html.parser",
    ).a
    plain = BeautifulSoup(f'<a href="{url}">Navigation</a>', "html.parser").a
    wrong_icon = BeautifulSoup(
        '<div class="pd-document16" style="background: url(\'/media/com_phocadownload/images/mime/16/icon-doc.png\')">'
        f'<a href="{url}">Document</a></div>',
        "html.parser",
    ).a
    assert is_pdf_candidate(marked, url)
    assert not is_pdf_candidate(plain, url)
    assert not is_pdf_candidate(wrong_icon, url)
    assert not is_pdf_candidate(marked, url.replace("1694:", "all:"))
