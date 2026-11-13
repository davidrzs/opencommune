from opencommune.crawl.linked_archive import LinkedSource, documents


def test_onegov_public_attachment_links_are_candidates_without_filename():
    listing = "https://municipality.example/topics/finance"
    source = LinkedSource(
        bfs_id=1, website="https://municipality.example", vendor="onegov", listing_urls=[listing]
    )
    path = "/storage/" + "a" * 64
    html = f'<a href="{path}">Budget</a><a href="https://other.example{path}">Other</a><a href="/storage/logo.svg">Logo</a>'
    assert documents(html, listing, source) == {"https://municipality.example" + path: listing}
    source.vendor = "custom"
    assert documents(html, listing, source) == {}


def test_quicksite_requires_reviewed_api_scope_and_keeps_document_provenance():
    from opencommune.crawl.discovery import page_links

    listing = "https://municipality.example/N7/documents.html"
    endpoint = "https://municipality.example/coreapi/elasticsearch/projects/town/document/search"
    source = LinkedSource(
        bfs_id=1,
        website="https://municipality.example",
        vendor="custom",
        listing_urls=[listing],
        crawl_prefixes=[listing],
    )
    html = '<script src="/coreapi/elasticsearch/projects/town/assets/js/elasticsearch.js"></script><div data-elasticsearch-project data-elasticsearch-view="document" data-elasticsearch-node="7"></div>'
    assert page_links(html, listing, source, {}) == []
    source.crawl_prefixes.append(endpoint)
    urls = page_links(html, listing, source, {})
    assert len(urls) == 1 and urls[0].startswith(endpoint + "?")
    result = '<div data-qsedit-editnode="12"><a href="/n12">Budget</a></div>'
    assert documents(result, urls[0], source) == {"https://municipality.example/n12": urls[0]}


def test_older_quicksite_candidates_and_pagination_stay_in_reviewed_scope():
    from opencommune.crawl.discovery import page_links

    listing = "https://municipality.example/documents-publics"
    ajax = "https://municipality.example/qsPortal/Ajax/get.asp"
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
    source = LinkedSource(
        bfs_id=1,
        website="https://municipality.example",
        vendor="custom",
        listing_urls=[listing],
        crawl_prefixes=[listing],
    )
    docs = documents(html, listing, source)
    assert docs == {"https://municipality.example/N4260/budget.html": listing}
    assert page_links(html, listing, source, docs) == []
    source.crawl_prefixes.append(ajax)
    assert page_links(html, listing, source, docs) == [
        ajax + "?Ajax=getnode&N=4107&NoLimitPage=1&page=2"
    ]


def test_hoststar_embedded_files_still_require_explicit_external_attribution():
    listing = "https://municipality.example/documents"
    external = "http://files.designer.hoststar.ch/aa/bb/id.pdf"
    source = LinkedSource(
        bfs_id=1, website="https://municipality.example", vendor="custom", listing_urls=[listing]
    )
    html = (
        '<script>Server.components = {"a":{"type":"widget.filedownload","data":{"url":"'
        + external
        + '"}}};</script>'
    )
    assert documents(html, listing, source) == {}
    source.document_urls = [external]
    assert documents(html, listing, source) == {external: listing}


def test_numeric_file_download_route_is_not_a_general_endpoint():
    listing = "https://municipality.example/documents"
    source = LinkedSource(
        bfs_id=1, website="https://municipality.example", vendor="custom", listing_urls=[listing]
    )
    html = '<a href="/files/get-file/1206">File</a><a href="/files/get-file/delete">Action</a>'
    assert documents(html, listing, source) == {
        "https://municipality.example/files/get-file/1206": listing
    }
