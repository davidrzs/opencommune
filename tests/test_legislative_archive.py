"""The legislative API reader follows only public pages and listed PDF attachments."""

import json
from pathlib import Path

import pytest

from opencommune.crawl.sites import legislative as archive

ORIGIN = "https://legislativo.example.test"
SEED = ORIGIN + "/api/public/legislations"
MESSAGES = archive.collection_url(ORIGIN, "messages", 5, 0)
FIXTURE = Path(__file__).parent / "fixtures/legislative_archive_page.json"


def test_legislatures_emit_only_listed_ids_and_five_observed_collections():
    payload = json.dumps([{"id": 5}, {"id": 4}])
    pdfs, children = archive.links(payload, SEED, ORIGIN)
    assert pdfs == []
    assert len(children) == 10
    assert children[0] == archive.collection_url(ORIGIN, "sessions", 5, 0)
    assert children[-1] == archive.collection_url(ORIGIN, "questions", 4, 0)
    assert all(archive.is_api_url(child, ORIGIN) for child in children)


def test_sanitized_page_emits_pdf_routes_and_next_page_only():
    pdfs, children = archive.links(FIXTURE.read_text(), MESSAGES, ORIGIN)
    assert pdfs == [
        ORIGIN + "/api/public/messages/563/messageText",
        ORIGIN + "/api/public/messages/563/attachments/3872",
    ]
    assert children == [archive.collection_url(ORIGIN, "messages", 5, 1)]
    data = json.loads(FIXTURE.read_text())
    data["hasNext"] = False
    data["pageNumber"] = 1
    assert (
        archive.links(json.dumps(data), archive.collection_url(ORIGIN, "messages", 5, 1), ORIGIN)[1]
        == []
    )


def test_false_has_next_cannot_silently_truncate_remaining_pages():
    data = json.loads(FIXTURE.read_text())
    data["hasNext"] = False
    with pytest.raises(ValueError, match="pagination"):
        archive.links(json.dumps(data), MESSAGES, ORIGIN)


@pytest.mark.parametrize(
    "route",
    [
        ORIGIN + "/api/public/questions?legislationId=1&page=0&size=100",
        ORIGIN + "/api/public/sessions?size=100&page=2&legislationId=9",
    ],
)
def test_exact_collection_query_keys_allow_order_changes(route):
    assert archive.is_api_url(route, ORIGIN)


@pytest.mark.parametrize(
    "route",
    [
        ORIGIN + "/api/public/messages?legislationId=5&page=0&size=14",
        ORIGIN + "/api/public/messages?legislationId=5&page=0&size=100&admin=1",
        ORIGIN + "/api/public/messages?legislationId=5&page=0&page=1&size=100",
        ORIGIN + "/api/public/messages?legislationId=0&page=0&size=100",
        ORIGIN + "/api/public/messages?legislationId=5&page=10000&size=100",
        ORIGIN + "/api/public/unknown?legislationId=5&page=0&size=100",
        "https://other.test/api/public/legislations",
        ORIGIN + "/api/public/legislations?all=1",
    ],
)
def test_unreviewed_requests_rejected(route):
    assert not archive.is_api_url(route, ORIGIN)


@pytest.mark.parametrize(
    "route,origin",
    [
        ("http://commune.test/docs", "http://commune.test"),
        ("https://[broken/api/public/legislations", ORIGIN),
        (ORIGIN + "/api/public/messages?legislationId=" + "9" * 5000 + "&page=0&size=100", ORIGIN),
        (ORIGIN + "/api/public/legislations", "https://[broken"),
    ],
)
def test_predicate_is_total_for_unrelated_or_malformed_listings(route, origin):
    assert not archive.is_api_url(route, origin)


@pytest.mark.parametrize(
    "payload",
    [
        "not JSON",
        "{}",
        "[]",
        '{"content":[],"pageNumber":0,"pageSize":100,"totalPages":2,"hasNext":"true"}',
        '{"content":[],"pageNumber":0,"pageSize":100,"totalPages":1,"hasNext":true}',
    ],
)
def test_invalid_page_schema_does_not_create_frontier(payload):
    with pytest.raises(ValueError):
        archive.links(payload, MESSAGES, ORIGIN)


def test_malformed_document_entries_are_skipped_without_losing_good_pdf():
    data = json.loads(FIXTURE.read_text())
    data["content"][0]["documents"].extend(
        [
            {"filename": "odd.pdf", "endpoint": "//other.test/api/public/messages/1/messageText"},
            {"filename": "odd.pdf", "endpoint": "/api/public/questions/1/questionText"},
            {"filename": "odd.pdf", "endpoint": "/api/public/messages/../admin"},
            {"filename": "odd.pdf", "endpoint": "/api/public/messages/1/attachments/2?admin=1"},
            {"filename": "odd.pdf", "endpoint": "https://[broken"},
            "malformed",
        ]
    )
    pdfs, _ = archive.links(json.dumps(data), MESSAGES, ORIGIN)
    assert len(pdfs) == 2


@pytest.mark.parametrize("payload", ['[{"id":true}]', '[{"id":5},{"id":5}]', "[]"])
def test_invalid_legislatures_rejected(payload):
    with pytest.raises(ValueError):
        archive.links(payload, SEED, ORIGIN)


def test_only_observed_attachment_routes():
    cases = {
        "sessions": ["agenda", "resolutionSummaries/2", "minutes/3"],
        "messages": ["messageText", "attachments/2", "commissionReports/3"],
        "motions": [
            "motionText",
            "preliminaryReport",
            "admissibilityReport",
            "attachments/2",
            "commissionReports/3",
        ],
        "interpellations": ["interpellationText", "attachments/2"],
        "questions": ["questionText", "municipalResponse", "attachments/2"],
    }
    for kind, tails in cases.items():
        url = archive.collection_url(ORIGIN, kind, 5, 0)
        data = {
            "content": [
                {
                    "documents": [
                        {
                            "filename": "a.pdf",
                            "endpoint": f"/api/public/{kind}/1/{tail}",
                        }
                        for tail in tails
                    ]
                }
            ],
            "pageNumber": 0,
            "pageSize": 100,
            "totalPages": 1,
            "hasNext": False,
        }
        pdfs, children = archive.links(json.dumps(data), url, ORIGIN)
        assert len(pdfs) == len(tails)
        assert children == []
