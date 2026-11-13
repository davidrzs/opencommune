"""Public bulletin pagination and schema failures without interpreting document text."""

import json

import pytest

from opencommune.crawl.sites import magnolia as archive

URL = "https://commune.test/municipality-ajax/bulletins?startIndex=0&maxResults=10"


def test_bulletin_pages_and_observed_pagination():
    rows = [
        {"pageURL": f"/news/{i}.html", "text": '<a href="/ignored.pdf">ignored</a>'}
        for i in range(10)
    ]
    found = archive.links(json.dumps({"results": rows}), URL)
    assert found[:-1] == [f"https://commune.test/news/{i}.html" for i in range(10)]
    assert found[-1] == URL.replace("startIndex=0", "startIndex=10")
    assert archive.links('{"results":[]}', found[-1]) == []


@pytest.mark.parametrize("payload", ["{}", "[]", '{"results":[{}]}', '{"results":"bad"}'])
def test_malformed_results_do_not_claim_empty_archive(payload):
    with pytest.raises(ValueError):
        archive.links(payload, URL)


@pytest.mark.parametrize(
    "query",
    [
        "startIndex=-1&maxResults=10",
        "startIndex=0&maxResults=1000",
        "startIndex=0&startIndex=10&maxResults=10",
        "startIndex=0&maxResults=10&action=delete",
    ],
)
def test_only_observed_pagination_parameters(query):
    assert archive.offset(URL.split("?")[0] + "?" + query) is None
