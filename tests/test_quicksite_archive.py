"""Quicksite URL extraction from the Aclens public widget and search markup."""

from urllib.parse import parse_qs, urlsplit

from opencommune.crawl.sites.quicksite import (
    document_urls,
    legacy_document_urls,
    legacy_page_urls,
    widget_urls,
)

LISTING = "https://www.aclens.ch/N671/reglements-communaux.html"
SCRIPT = "/coreapi/elasticsearch/projects/aclens26/assets/js/elasticsearch.js?ts=20250204"
RESULT = "https://www.aclens.ch/coreapi/elasticsearch/projects/aclens26/document/search?q=&elasticsearchNode=671"


def test_widget_uses_observed_project_and_document_scope():
    html = f"""
    <script src="{SCRIPT}"></script>
    <div data-elasticsearch-project data-elasticsearch-view="default"
         data-elasticsearch-pagesize="5"></div>
    <section data-elasticsearch-project data-elasticsearch-node="671"
      data-elasticsearch-pagesize="60" data-elasticsearch-nodetype=""
      data-elasticsearch-parentnode="671" data-elasticsearch-sort=""
      data-elasticsearch-view="document" data-elasticsearch-query="input.query-full"
      data-elasticsearch-result="#search-result-list-full"
      data-elasticsearch-filtertags="" data-elasticsearch-initresult="true"></section>
    """
    urls = widget_urls(html, LISTING)
    assert len(urls) == 1
    parts = urlsplit(urls[0])
    assert parts.path == "/coreapi/elasticsearch/projects/aclens26/document/search"
    query = parse_qs(parts.query, keep_blank_values=True)
    assert query == {
        "q": [""],
        "elasticsearchProject": [""],
        "elasticsearchNode": ["671"],
        "elasticsearchPagesize": ["60"],
        "elasticsearchNodetype": [""],
        "elasticsearchParentnode": ["671"],
        "elasticsearchSort": [""],
        "elasticsearchView": ["document"],
        "elasticsearchQuery": ["input.query-full"],
        "elasticsearchResult": ["#search-result-list-full"],
        "elasticsearchFiltertags": [""],
        "elasticsearchInitresult": ["true"],
    }


def test_widget_rejects_global_and_unproven_searches():
    scoped = '<section data-elasticsearch-project data-elasticsearch-view="document" data-elasticsearch-parentnode="671"></section>'
    assert widget_urls(f'<script src="{SCRIPT}"></script>{scoped}', LISTING)
    assert (
        widget_urls(f'<script src="{SCRIPT}"></script>{scoped.replace("671", "0")}', LISTING) == []
    )
    assert (
        widget_urls(f'<script src="{SCRIPT}"></script>{scoped.replace("671", "x")}', LISTING) == []
    )
    assert widget_urls(scoped, LISTING) == []
    assert (
        widget_urls(
            '<script src="https://elsewhere.example/coreapi/elasticsearch/projects/aclens26/assets/js/elasticsearch.js"></script>'
            + scoped,
            LISTING,
        )
        == []
    )
    assert (
        widget_urls(
            '<script src="/coreapi/elasticsearch/projects/../assets/js/elasticsearch.js"></script>'
            + scoped,
            LISTING,
        )
        == []
    )


def test_result_requires_matching_card_id_and_same_host():
    html = """
    <div data-qsedit-editnode="976">
      <a href="https://www.aclens.ch/n976">Directive du règlement</a>
      <a href="/n976">same document again</a>
      <a href="/n975">different document</a>
      <a href="https://other.example/n976">other host</a>
      <a href="/N976/directive.html">different route</a>
    </div>
    <div data-qsedit-editnode="975"><a href="/n975">Règlement</a></div>
    <div data-qsedit-editnode="bad"><a href="/n977">bad card</a></div>
    <a href="/n978">outside card</a>
    """
    assert document_urls(html, RESULT) == [
        "https://www.aclens.ch/n976",
        "https://www.aclens.ch/n975",
    ]
    assert document_urls(html, LISTING) == []


def test_result_rejects_ambiguous_and_action_links():
    html = """
    <div data-qsedit-editnode="976"><a href="/n976?delete=1">action</a></div>
    <div data-qsedit-editnode="0"><a href="/n0">zero</a></div>
    <div data-qsedit-editnode="977"><div data-qsedit-editnode="978">
      <a href="/n977">belongs to neither card</a>
      <a href="/n978">nested card</a>
    </div></div>
    """
    assert document_urls(html, RESULT) == ["https://www.aclens.ch/n978"]


def test_observed_scoped_view_variants():
    # Givrins uses cards, Ropraz documentconseil, and Pompaples
    # documentconseildates. Each still carries an edit-node ID on the card.
    for view in ("cards", "documentconseil", "documentconseildates"):
        page = (
            f'<script src="{SCRIPT}"></script>'
            f'<section data-elasticsearch-project data-elasticsearch-node="671" '
            f'data-elasticsearch-parentnode="671" data-elasticsearch-view="{view}"></section>'
        )
        api = widget_urls(page, LISTING)
        assert len(api) == 1
        assert f"/{view}/search?" in api[0]
        result = '<div data-qsedit-editnode="976"><a href="/n976">Document</a></div>'
        assert document_urls(result, api[0]) == ["https://www.aclens.ch/n976"]


def test_widget_rejects_unknown_view():
    page = (
        f'<script src="{SCRIPT}"></script>'
        '<section data-elasticsearch-project data-elasticsearch-node="671" '
        'data-elasticsearch-view="admin"></section>'
    )
    assert widget_urls(page, LISTING) == []


def test_legacy_document_candidates_require_provenance_and_document_container():
    # The document-list and child-icon containers come from Commugny and
    # Pompaples; the article layout comes from Gingins.
    html = f"""
    <script src="{SCRIPT}"></script>
    <nav><a target="_blank" href="/N100/menu.html">menu</a></nav>
    <main>
      <a target="_blank" href="/N101/ordinary-page.html">outside document list</a>
      <section class="tplListDocuments">
        <a target="_blank" href="/N102/reglement.html">regulation</a>
        <a target="_blank" href="https://other.example/N103/file.html">external</a>
        <a href="/N104/not-new-tab.html">ordinary link</a>
      </section>
      <section class="tplDphChildsIcons">
        <a target="_blank" href="/N105/another-regulation.html">Voir le document</a>
      </section>
      <article><a target="_blank" href="/N106/third.html">Reglement</a></article>
      <article><a target="_blank" href="/N107/third.html?delete=1">action</a></article>
    </main>
    """
    assert legacy_document_urls(html, LISTING) == [
        "https://www.aclens.ch/N102/reglement.html",
        "https://www.aclens.ch/N105/another-regulation.html",
        "https://www.aclens.ch/N106/third.html",
    ]
    assert (
        legacy_document_urls(html.replace(SCRIPT, "https://other.example" + SCRIPT), LISTING) == []
    )


def test_older_quicksite_download_card_requires_pdf_metadata_and_icon():
    html = """
    <meta name="generator" content="CMS - Quicksite www.quicksite.ch">
    <script src="/qsPortal/Javascript/qs.min.js"></script>
    <div class="tplDocumentItem">Budget 2024 <p>pdf 3 Mb</p>
      <a class="icon-download" target="_blank" href="/N4260/budget-2024.html">Download</a>
    </div>
    <div class="tplDocumentItem">ordinary page
      <a class="icon-download" target="_blank" href="/N4261/page.html">Download</a>
    </div>
    """
    assert legacy_document_urls(html, LISTING) == ["https://www.aclens.ch/N4260/budget-2024.html"]
    assert (
        legacy_document_urls(html.replace("/qsPortal/Javascript/qs.min.js", "/app.js"), LISTING)
        == []
    )


def test_older_summary_card_requires_matching_download_node():
    html = f"""
    <script src="{SCRIPT}"></script>
    <div class="tplDocumentSummaryItem">pdf 898 Kb
      <a title="Voir le détail" href="/N20188/postulat.html">Postulat</a>
      <a title="Télécharger le document" href="/qsPortal/Home.asp?N=20188&amp;DocAction=Download">PDF</a>
    </div>
    <div class="tplDocumentSummaryItem">pdf 200 Kb
      <a title="Voir le détail" href="/N20189/other.html">Other</a>
      <a title="Télécharger le document" href="/qsPortal/Home.asp?N=20190&amp;DocAction=Download">Wrong node</a>
    </div>
    """
    assert legacy_document_urls(html, LISTING) == [
        "https://www.aclens.ch/qsPortal/Home.asp?N=20188&DocAction=Download"
    ]


def test_older_quicksite_form_pagination_uses_observed_page_parameter():
    html = f"""
    <script src="{SCRIPT}"></script>
    <form name="NodeListForm_0"><input type="hidden" name="Page_0" value="1"></form>
    <div class="pagination" data-parampagename="Page_0" data-formname="NodeListForm_0">
      <a href="#p2">2</a><a href="#p3">3</a><a href="#p0">bad</a>
    </div>
    """
    assert legacy_page_urls(html, "https://www.aclens.ch/documents") == [
        "https://www.aclens.ch/documents?Page_0=2",
        "https://www.aclens.ch/documents?Page_0=3",
    ]
    assert legacy_page_urls(html.replace(SCRIPT, "/app.js"), LISTING) == []


def test_older_quicksite_ajax_page_is_bound_to_observed_node():
    html = """
    <meta name="generator" content="CMS - Quicksite www.quicksite.ch">
    <script src="/qsPortal/Javascript/qs.min.js"></script>
    <script>gobjSessionVar.lngCurrentNodeFK = 4107;</script>
    <div class="tplSearchDocuments" id="a4107">
      <div class="tplDocumentItem">pdf 3 Mb
        <a class="icon-download" target="_blank" href="/N4260/budget.html">Download</a>
      </div>
      <a class="lazy-button" href="javascript:;">More</a>
    </div>
    """
    first = "https://www.aclens.ch/documents-publics"
    second = "https://www.aclens.ch/qsPortal/Ajax/get.asp?Ajax=getnode&NoLimitPage=1&N=4107&page=2"
    assert legacy_page_urls(html, first) == [second]
    fragment = html.split('<div class="tplSearchDocuments"', 1)[1]
    fragment = '<div class="tplSearchDocuments"' + fragment
    assert legacy_document_urls(fragment, second) == ["https://www.aclens.ch/N4260/budget.html"]
    assert legacy_page_urls(fragment, second) == [second.replace("page=2", "page=3")]
    assert legacy_document_urls(fragment, second.replace("N=4107", "N=4108")) == []


def test_archive_folder_cards_remain_scoped_navigation():
    from opencommune.crawl.discovery import page_links
    from opencommune.crawl.linked_archive import LinkedSource

    listing = "https://www.example.ch/coreapi/elasticsearch/projects/example/cards/search?elasticsearchNode=10"
    html = """
    <div class="card qs-edit-index" data-qsedit-editnode="20">
      <a href="/n20">Previous legislature</a>
    </div>
    <div data-qsedit-editnode="21"><a href="/n21">Budget</a></div>
    <a href="https://other.example/n22">External folder</a>
    """
    source = LinkedSource(
        bfs_id=1,
        website="https://www.example.ch",
        vendor="custom",
        listing_urls=[listing],
        crawl_prefixes=["https://www.example.ch/n20"],
    )
    files = document_urls(html, listing)
    assert files == ["https://www.example.ch/n21"]
    assert page_links(html, listing, source, files) == ["https://www.example.ch/n20"]


def test_older_bootstrap_download_icons_and_named_pagination():
    listing = "https://www.commune.ch/N1707/journal.html"
    html = """<meta name="generator" content="CMS Quicksite">
    <script src="/qsPortal/Javascript/qs.min.js"></script>
    <div class="tplDphChildsLinks"><a href="/N40/journal.html"><span class="glyphicon glyphicon-download"></span>Journal</a>
    <a href="/N41/contact.html">Contact</a>
    <a href="https://elsewhere.example/N42/file.html"><span class="glyphicon glyphicon-download"></span>Other</a></div>
    <form name="NodeListForm_dphchildslinks" action=""><input type="hidden" name="Page_dphchildslinks" value="1"></form>
    <div class="pagination" data-parampagename="Page_dphchildslinks" data-formname="NodeListForm_dphchildslinks"><a href="#p2">2</a></div>"""
    assert legacy_document_urls(html, listing) == ["https://www.commune.ch/N40/journal.html"]
    assert legacy_page_urls(html, listing) == [listing + "?Page_dphchildslinks=2"]
    assert (
        legacy_page_urls(html.replace('action=""', 'action="https://elsewhere.example"'), listing)
        == []
    )
    assert legacy_page_urls(html.replace('action=""', 'method="post"'), listing) == []
