"""Sitemap XML expands only a source's reviewed archive sections."""

import pytest

from opencommune.crawl.linked_archive import LinkedSource
from opencommune.crawl.sitemaps import sitemap_links

ROOT = "https://www.renens.ch/sitemap.xml"
CHILD = "https://www.renens.ch/sitemap/fr_1.xml"
DETAIL = "https://www.renens.ch/officielle/autorites/documents/budget-2026-1"
SOURCE = LinkedSource(
    bfs_id=5591,
    website="https://www.renens.ch/",
    vendor="iomedia-nuxt",
    listing_urls=[ROOT],
    crawl_prefixes=[
        "https://www.renens.ch/sitemap/",
        "https://www.renens.ch/officielle/autorites/documents/",
    ],
)


def test_index_yields_only_reviewed_same_host_xml_children():
    xml = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://www.renens.ch/sitemap/fr_1.xml</loc></sitemap>
      <sitemap><loc>https://www.renens.ch/sitemap/fr_1.xml</loc></sitemap>
      <sitemap><loc>https://www.renens.ch/other/fr_2.xml</loc></sitemap>
      <sitemap><loc>https://renens.ch/sitemap/fr_2.xml</loc></sitemap>
      <sitemap><loc>https://evil.example/sitemap/fr_3.xml</loc></sitemap>
      <sitemap><loc>https://www.renens.ch/officielle/autorites/documents/not-xml</loc></sitemap>
    </sitemapindex>"""
    assert sitemap_links(xml, ROOT, SOURCE) == [CHILD]


def test_urlset_yields_only_reviewed_detail_pages():
    xml = f"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>{DETAIL}</loc></url>
      <url><loc>https://www.renens.ch/officielle/autorites/documents/other-2</loc></url>
      <url><loc>https://www.renens.ch/officielle/autorites/seances/other-3</loc></url>
      <url><loc>https://renens.allinone.io/api/contents</loc></url>
    </urlset>"""
    assert sitemap_links(xml, CHILD, SOURCE) == [
        DETAIL,
        "https://www.renens.ch/officielle/autorites/documents/other-2",
    ]


@pytest.mark.parametrize(
    "xml",
    [
        "<urlset>",
        "<not-sitemap/>",
        "<urlset><url/></urlset>",
        "<urlset><sitemap><loc>https://www.renens.ch/sitemap/fr_1.xml</loc></sitemap></urlset>",
        "<!DOCTYPE sitemap [<!ENTITY x 'bad'>]><urlset/>",
    ],
)
def test_malformed_or_wrong_shape_is_an_error(xml):
    with pytest.raises(ValueError):
        sitemap_links(xml, ROOT, SOURCE)


def test_source_must_review_the_seed():
    with pytest.raises(ValueError):
        sitemap_links("<urlset/>", "https://www.renens.ch/other/sitemap.xml", SOURCE)
