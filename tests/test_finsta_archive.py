"""Published finance controls, exact municipal scope and resumable year expansion."""

from urllib.parse import parse_qs, urlsplit

import pytest

from opencommune.crawl.linked_archive import LinkedSource
from opencommune.crawl.sites.finsta import FinstaExports, ReportChoice, from_selector

ENDPOINT = "http://publisher.test/native-report-root"
HOST = "https://commune.test"


def selector():
    def select(name, values):
        return (
            f'<select id="{name}">'
            + "".join(f'<option value="{value}">{label}</option>' for value, label in values)
            + "</select>"
        )

    return (
        '<script>var url = "'
        + ENDPOINT
        + '/Pages/ReportViewer.aspx?%2fReports_BE%2f" + reportName;</script>'
        + select("GemeindeByName", [(1, "Commune"), (2, "Other"), (2, "Other/Autre")])
        + select("GemeindeByBfsNr", [(1, "1"), (2, "2"), (2, "2")])
        + select("SelectedFinancialYear", [(2016, "2016"), (2024, "2024"), (2025, "2025")])
        + select(
            "ReportName",
            [
                ("Bil_Aktiven_DE", "Balance"),
                ("ER_Einzelauszug_Funktionsstufen_DE", "Function details"),
                ("Einzelauszug_Sachgruppen_DE", "Account details"),
                ("KPI_HRM2_DE", "Indicators"),
            ],
        )
        + select("Funktionsstufe1", [(0, "Administration"), (2, "Education")])
        + select("Kontokennung", [(3, "Expenses"), (4, "Income")])
        + select("KPI", [(3, "Debt"), (9, "Self-financing")])
    )


def exports(years=(2016,)):
    return FinstaExports(
        endpoint=ENDPOINT,
        folder="/Reports_BE/",
        years=list(years),
        reports=[ReportChoice(name="Bil_Aktiven_DE")],
    )


def test_all_published_years_and_first_level_choices_without_guessed_ids():
    config = from_selector(selector(), ENDPOINT, 1, "Commune")
    assert config.years == [2016, 2024, 2025]  # no latest-year hardcode
    assert len(config.reports) == 7
    urls = list(config.urls(1))
    assert len(urls) == 21 and len(set(urls)) == 21
    for url in urls:
        query = parse_qs(urlsplit(url).query)
        assert query["BFS_Nr"] == ["1"]
        assert query["rs:Format"] == ["PDF"]
        assert query["Absolut_Relativ"] == ["1"]
        assert "Funktionsstufe2" not in query and "Sachgruppe" not in query
    assert any("Funktionsstufe1=0" in url for url in urls)


@pytest.mark.parametrize(
    "html,endpoint,name",
    [
        (selector().replace('value="1">Commune', 'value="99">Commune'), ENDPOINT, "Commune"),
        (selector(), ENDPOINT, "Wrong commune"),
        (selector(), ENDPOINT + "-changed", "Commune"),
        (selector().replace('id="KPI"', 'id="Gone"'), ENDPOINT, "Commune"),
        (selector().replace('value="2016"', 'value="2024"'), ENDPOINT, "Commune"),
    ],
)
def test_changed_identity_controls_or_endpoint_require_review(html, endpoint, name):
    with pytest.raises(ValueError):
        from_selector(html, endpoint, 1, name)


@pytest.mark.parametrize(
    "name,parameters",
    [
        ("Bil_Aktiven_DE", {"BFS_Nr": "2"}),
        ("KPI_HRM2_DE", {}),
        ("KPI_HRM2_DE", {"KPI": "-1"}),
        ("ER_Einzelauszug_Funktionsstufen_DE", {"Funktionsstufe1": "2", "Funktionsstufe2": "21"}),
        ("../other", {}),
    ],
)
def test_selector_overrides_and_incomplete_reports_are_rejected(name, parameters):
    with pytest.raises(ValueError):
        ReportChoice(name=name, parameters=parameters)


def test_generated_files_are_exact_not_a_shared_publisher_scope():
    config = LinkedSource(
        bfs_id=1,
        website=HOST,
        vendor=None,
        finsta_exports=exports(),
        attribution_note="Reviewed official report controls and BFS identity",
    )
    url = config.selected_documents[0]
    assert config.allows(url)
    for altered in [
        url.replace("BFS_Nr=1", "BFS_Nr=2"),
        url.replace("Buchjahr=2016", "Buchjahr=2015"),
        url.replace("rs:Format=PDF", "rs:Format=HTML4.0"),
        url + "&BFS_Nr=2",
        ENDPOINT,
        ENDPOINT + "/report.pdf",
    ]:
        assert not config.allows(altered)
    assert not config.allows_listing(url) and not config.allows_listing(ENDPOINT)
    with pytest.raises(ValueError, match="attribution"):
        LinkedSource(bfs_id=1, website=HOST, vendor=None, finsta_exports=exports())
