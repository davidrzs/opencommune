"""Unit tests for the html_links adapter on small inline pages; recorded pages live in tests/fixtures."""

import pytest

from opencommune.crawl.adapters.html_links import HtmlLinksAdapter, clean_text
from opencommune.schemas import AdapterStep

BASE = "https://www.example.ch/politik/protokolle"


def links(html: str, parent=None, **step):
    return HtmlLinksAdapter().extract_links(
        html, BASE, AdapterStep(**step), None, "dmy", parent=parent
    )


def test_title_attribute_replaces_generic_text_and_supplies_the_date():
    html = """
    <a class="pdf" title="Beschluesse der 520. Sitzung vom 22.06.2026" href="/docs/Beschluesse-der-520.-Sitzung.pdf">Beschluesse der 520. Sitzung</a>
    <a class="button" title="1. Sitzung des Gemeinderates vom 28.01.2026" href="/docs/gr-1.pdf"><span> PDF </span></a>
    <a title="Sitzungsdaten 2026/2027" href="/docs/daten.pdf">Sitzungsdaten 2026/2027</a>
    """
    out = links(html, selector="a[href$='.pdf']")
    assert [(link.text, link.date and link.date.isoformat()) for link in out] == [
        ("Beschluesse der 520. Sitzung", "2026-06-22"),  # text kept, date from the title
        ("1. Sitzung des Gemeinderates vom 28.01.2026", "2026-01-28"),  # generic text replaced
        ("Sitzungsdaten 2026/2027", None),
    ]


def test_text_regex_applies_to_the_title_that_replaced_a_generic_label():
    html = '<a title="Protokoll der Sitzung vom 3.7.2025" href="/a.pdf">Download PDF</a><a title="Traktanden" href="/b.pdf">Download PDF</a>'
    out = links(html, selector="a", text_regex="^Protokoll")
    assert [link.url for link in out] == ["https://www.example.ch/a.pdf"]


def test_file_size_tails_are_stripped_from_the_text():
    assert clean_text("Protokoll [pdf, 162 KB]") == "Protokoll"
    assert clean_text("PV de la séance Fichier PDF (212.84 Ko)") == "PV de la séance"
    assert (
        clean_text("Gemeindeversammlung vom 11.06.2026 0.88 MB")
        == "Gemeindeversammlung vom 11.06.2026"
    )
    assert clean_text("Rechnung 2025") == "Rechnung 2025"


def test_relative_hrefs_resolve_against_base_href():
    html = '<head><base href="https://www.example.ch/"></head><body><a href="inhalte/gv/20241120_protokoll.pdf">November 2024</a></body>'
    out = links(html, selector="a")
    assert out[0].url == "https://www.example.ch/inhalte/gv/20241120_protokoll.pdf"
    out = links('<a href="inhalte/gv/x.pdf">x</a>', selector="a")
    assert (
        out[0].url == "https://www.example.ch/politik/inhalte/gv/x.pdf"
    )  # no base element: the page URL


def test_anchor_text_is_nfc_normalised_and_freed_of_soft_hyphens_before_matching():
    decomposed = (
        "28. April 2026 Ausführliches Protokoll"  # u + combining diaeresis, as bs.ch renders it
    )
    shy = "Pro­tokoll Bud­get­ge­meinde-Ver­samm­lung vom 27.11.2025"
    html = f'<a href="/a.pdf">{decomposed}</a><a href="/b.pdf">{shy}</a>'
    out = links(html, selector="a", text_regex="Ausführliches Protokoll|^Protokoll Budget")
    assert [link.text for link in out] == [
        "28. April 2026 Ausführliches Protokoll",
        "Protokoll Budgetgemeinde-Versammlung vom 27.11.2025",
    ]
    assert [link.date.isoformat() for link in out] == ["2026-04-28", "2025-11-27"]


def test_undated_document_inherits_the_date_of_the_link_that_led_to_its_page():
    import datetime as dt

    from opencommune.crawl.adapters import Link

    parent = Link(
        url="https://www.example.ch/sitzungen/1051",
        text="Ebene 2: 12.09.2025",
        date=dt.date(2025, 9, 12),
    )
    html = '<a href="/assets/1/Protokoll ER-Sitzung.pdf">Protokoll ER-Sitzung</a><a href="/assets/2/Beschluesse vom 24.10.2025.pdf">Beschluesse</a>'
    inherited, own = links(html, parent=parent, selector="a")
    assert (
        inherited.date == inherited.context_date == dt.date(2025, 9, 12)
        and inherited.date_precision == "day"
    )
    assert (
        own.date == dt.date(2025, 10, 24) and own.context_date is None
    )  # the document's own date wins
    assert links(html, parent=None, selector="a")[0].date is None
    month = Link(url="x", text="Juni 2026", date=dt.date(2026, 6, 1), date_precision="month")
    assert links(html, parent=month, selector="a")[0].date_precision == "month"


def test_row_context_supplies_title_and_date_when_the_anchor_has_none():
    html = """
    <table><tr><td>Freitag</td><td>17. April 2026</td><td>19.30 Uhr</td><td><a href="/assets/1/PROT_GV.pdf">Protokoll der GV</a></td></tr></table>
    <ul class="uploads-list"><li><span><strong>Protokoll Einwohnergemeindeversammlung vom 24. November 2025</strong></span>
        <a href="/fileadmin/Protokolle/Protokoll_EGV.pdf">Herunterladen</a></li></ul>
    <p>21 avril 2026 : <a href="/u/CG-03.31.26-Convocation.pdf">ordre du jour</a> et <a href="/u/05.07.26-CG-P.V.pdf">procès-verbal</a><br>
       5 mai 2026: <a href="/u/04.14.26-convocation.pdf">ordre du jour</a> et <em><a href="/u/05.05.26.p.v.provisoire.pdf">procès-verbal provisoire</a></em></p>
    """
    out = links(html, selector="a", context="row")
    by_url = {link.url.rsplit("/", 1)[-1]: link for link in out}
    gv = by_url["PROT_GV.pdf"]
    assert (gv.text, gv.date.isoformat(), gv.context_date.isoformat()) == (
        "Protokoll der GV",
        "2026-04-17",
        "2026-04-17",
    )
    egv = by_url["Protokoll_EGV.pdf"]
    assert (
        egv.text == "Protokoll Einwohnergemeindeversammlung vom 24. November 2025"
        and egv.date.isoformat() == "2025-11-24"
    )
    assert by_url["05.07.26-CG-P.V.pdf"].date.isoformat() == "2026-04-21"  # first paragraph segment
    assert (
        by_url["05.05.26.p.v.provisoire.pdf"].date.isoformat() == "2026-05-05"
    )  # after the line break
    assert links(html, selector="a")[0].date is None  # without the opt-in the row is not read


def test_row_date_after_vom_wins_over_the_publication_date_before_it():
    html = '<li><div>11. Dezember 2025</div><div>Beschlüsse der Gemeindeversammlung vom 10. Dezember 2025</div><a href="/de/Medienmitteilung_GV_Dez_2025.pdf">Mehr erfahren</a></li>'
    (link,) = links(html, selector="a", context="row")
    assert link.date.isoformat() == "2025-12-10" and link.text.startswith(
        "11. Dezember 2025 Beschlüsse der Gemeindeversammlung vom 10. Dezember 2025"
    )


def test_also_documents_reads_the_last_step_on_the_listing_page_too():
    from opencommune.schemas import AdapterConfig

    html = """<p><a href="/system/files/download/2026%2007%2002%20Protokoll.pdf">- Protokoll GV 02.07.2026</a><br>
    <a href="/node/5255">- Protokoll GV 22.04.2026</a> <a href="/node/5232">- Botschaft GV 22.04.2026</a></p>"""
    cfg = AdapterConfig(
        steps=[
            AdapterStep(selector="a[href*='/node/']", text_regex="Protokoll", also_documents=True),
            AdapterStep(selector="a[href*='/system/files/']", text_regex="Protokoll"),
        ]
    )
    pages = links(html, **cfg.steps[0].model_dump())
    docs = links(html, **cfg.steps[-1].model_dump())
    assert [link.url for link in pages] == ["https://www.example.ch/node/5255"] and pages[
        0
    ].date.isoformat() == "2026-04-22"
    assert [link.date.isoformat() for link in docs] == ["2026-07-02"] and docs[0].url.endswith(
        "Protokoll.pdf"
    )
    assert cfg.steps[0].also_documents and not cfg.steps[1].also_documents


def test_next_url_follows_the_configured_next_page_link():
    adapter = HtmlLinksAdapter()
    step = AdapterStep(
        selector="a", next_selector="link[rel=next], a[rel=next], li.pager__item--next"
    )
    head = '<head><link rel="next" href="/politik/protokolle?page=2&amp;cHash=bb41"></head>'
    assert (
        adapter.next_url(head, BASE, step)
        == "https://www.example.ch/politik/protokolle?page=2&cHash=bb41"
    )
    pager = '<ul><li class="pager__item--next"><a href="?page=3">Suivant</a></li></ul>'
    assert (
        adapter.next_url(pager, BASE + "?page=2", step)
        == "https://www.example.ch/politik/protokolle?page=3"
    )
    assert (
        adapter.next_url('<a rel="next" href="?page=2">next</a>', BASE + "?page=2", step) is None
    )  # points at itself
    assert adapter.next_url("<p>last page</p>", BASE, step) is None
    assert adapter.next_url(head, BASE, AdapterStep(selector="a")) is None  # opt-in


def test_onclick_rows_and_window_open_anchors_are_links():
    html = """
    <table><tr class="row" onClick="location.href='/pages/rpc/media_sav.cfm?medId=205512';"><td><img src="i.gif"></td>
      <td><div>Gemeindeversammlung vom 11.06.2026</div></td><td><div>0.88 MB</div></td></tr></table>
    <a onclick='window.open("https://moutier.ch/wp-content/uploads/2023/01/03.00_PV-23.02.2026.pdf");return false;' href="#"><span>PV 400 23.02.2026</span></a>
    <a href="#top">Seitenanfang</a>
    """
    rows = links(html, selector="tr[onclick]")
    assert [(link.url, link.text, link.date.isoformat()) for link in rows] == [
        (
            "https://www.example.ch/pages/rpc/media_sav.cfm?medId=205512",
            "Gemeindeversammlung vom 11.06.2026",
            "2026-06-11",
        )
    ]
    anchors = links(html, selector="a")
    assert [(link.url, link.text) for link in anchors] == [
        (
            "https://moutier.ch/wp-content/uploads/2023/01/03.00_PV-23.02.2026.pdf",
            "PV 400 23.02.2026",
        )
    ]
    assert (
        len(links(html, selector="table")) == 1
    )  # a container selector finds the clickable row inside


@pytest.mark.parametrize(
    "text,expected",
    [
        ("PV_seance_CC_29.06.15.pdf", "2015-06-29"),  # two-digit year
        ("Protokoll_Gemeindeversammlung_24.11.25.pdf", "2025-11-24"),
        ("16. Jun. 2025, 19:00 – 22:00 Uhr", "2025-06-16"),  # abbreviated month
        ("23. Nov. 2026, 20:00", "2026-11-23"),
        ("séance du 1 sept. 2025", "2025-09-01"),
        ("12 févr. 2026", "2026-02-12"),
        ("seduta del 3 dic. 2025", "2025-12-03"),
        ("GV_Einwohnergemeinde_Protokoll_10-12-2025.pdf", "2025-12-10"),  # dd-mm-yyyy
        ("ERS_22_01_2025.pdf", "2025-01-22"),  # dd_mm_yyyy
        ("2026 04 22 Protokoll.pdf", "2026-04-22"),  # yyyy mm dd
        (
            "Budget 2025 10 000 Franken",
            None,
        ),  # an invalid ymd match does not hide anything, nor is it a date
        ("Version 2025-13-40 und 3.7.2025", "2025-07-03"),  # an invalid first shape falls through
        ("GV-Protokoll-Juni-2026.pdf", None),  # month and year only are not an exact date
        ("Sitzung 19.30 Uhr", None),
    ],
)
def test_more_date_shapes(text, expected):
    from opencommune.crawl.adapters.html_links import parse_date

    got = parse_date(text)
    assert (got.isoformat() if got else None) == expected


def test_month_and_year_only_give_an_approximate_date_flagged_on_the_link():
    import datetime as dt

    from opencommune.crawl.adapters import Link
    from opencommune.crawl.adapters.html_links import parse_month_year

    assert parse_month_year("GV-Protokoll-Juni-2026.pdf") == dt.date(2026, 6, 1)
    assert parse_month_year("Protokoll ER-Sitzung September 2025") == dt.date(2025, 9, 1)
    assert parse_month_year("Rechnung 2025") is None
    html = '<a href="/protokolle/GV-Protokoll-Juni-2026.pdf">GV Protokoll Juni 2026</a><a href="/p/Protokoll-18.06.2026.pdf">Protokoll 18.06.2026</a>'
    approx, exact = links(html, selector="a")
    assert (approx.date, approx.date_precision) == (dt.date(2026, 6, 1), "month")
    assert (exact.date, exact.date_precision) == (dt.date(2026, 6, 18), "day")
    # the folder link of the previous hop names the day within that month
    folder = Link(url="x", text="Ebene 2: 12.09.2025", date=dt.date(2025, 9, 12))
    (link,) = links(
        '<a href="/a/Protokoll ER-Sitzung September 2025.pdf">Protokoll ER-Sitzung September 2025</a>',
        parent=folder,
        selector="a",
    )
    assert (link.date, link.date_precision, link.context_date) == (
        dt.date(2025, 9, 12),
        "day",
        dt.date(2025, 9, 12),
    )
    other = Link(url="x", text="Ebene 2: 24.10.2025", date=dt.date(2025, 10, 24))
    (link,) = links(
        '<a href="/a/x.pdf">Protokoll ER-Sitzung September 2025</a>', parent=other, selector="a"
    )
    assert (link.date, link.date_precision) == (
        dt.date(2025, 9, 1),
        "month",
    )  # a different month: the document's own month stands


def test_a_full_date_in_the_row_outranks_a_two_digit_year_in_the_file_name():
    html = '<p>21 avril 2026 : <a href="/u/05.07.26-CG-P.V.-21.04.26-signe.pdf">procès-verbal</a></p><a href="/d/PV_seance_CC_29.06.15.pdf">Procès-verbal</a>'
    with_row, plain = links(html, selector="a", context="row")
    assert with_row.date.isoformat() == "2026-04-21" and with_row.context_date is not None
    assert plain.date.isoformat() == "2015-06-29" and plain.context_date is None


def test_the_two_separators_of_a_date_must_match():
    from opencommune.crawl.adapters.html_links import parse_date

    assert (
        parse_date(
            "Gemeindeversammlung vom Mittwoch, 4. Dezember 2002 04.12.2002, 20.15 Uhr"
        ).isoformat()
        == "2002-12-04"
    )
    assert parse_date("Sitzung 2026 04.12") is None


def test_two_digit_years_beyond_next_year_belong_to_the_last_century():
    from opencommune.crawl.adapters.html_links import parse_date

    assert parse_date("PQ-Es-Condemines-24.07.96.pdf").isoformat() == "1996-07-24"
    assert parse_date("Protokoll 05.07.26").isoformat() == "2026-07-05"
    assert parse_date("PQ-Au-Revelin-24.03.81.pdf") is None  # before 1990
    # the year's last two digits are not a day: "2019-November-29" is not 19 November 2029
    assert parse_date("Traktandenliste-2019-November-29.pdf") is None
    assert parse_date("Protokoll 29. November 2019").isoformat() == "2019-11-29"


def test_the_earliest_full_date_in_a_string_wins():
    from opencommune.crawl.adapters.html_links import parse_date

    # a two-day session folder: the day-first date at the start, not the year-first artefact inside it
    assert (
        parse_date(
            "/protokolle-beschluesse/2025/02-12-2025-03-12-2025/ERS_02_12_2025_03_12_2025.pdf"
        ).isoformat()
        == "2025-12-02"
    )
    assert (
        parse_date("Sitzung 1.2.10 vom 3.7.2025").isoformat() == "2025-07-03"
    )  # a full shape outranks a two-digit year anywhere


def test_row_context_prefers_the_cell_when_it_carries_a_date():
    """Two documents side by side in one table row, each cell with its own date."""
    import datetime as dt

    html = (
        "<table><tr>"
        "<td><a href='/a.pdf'>Budget 2026</a> - 10.12.2025</td>"
        "<td><a href='/b.pdf'>Comptes 2024</a> - 04.06.2025</td>"
        "</tr><tr><td>Séance du 3 mars 2025</td><td><a href='/c.pdf'>PV</a></td></tr></table>"
    )
    got = links(html, selector="a[href$='.pdf']", context="row")
    assert [(link.text, link.date) for link in got] == [
        ("Budget 2026", dt.date(2025, 12, 10)),
        ("Comptes 2024", dt.date(2025, 6, 4)),
        ("PV", dt.date(2025, 3, 3)),  # the cell has no date, the row does
    ]


def test_custom_date_regex_accepts_a_month_name_in_the_middle_group():
    import datetime as dt

    from opencommune.crawl.adapters.html_links import parse_date

    year_first = r"(\d{4})_([a-zéû]+)_(\d{1,2})"
    assert parse_date("cm_pv_2024_avril_16", year_first, "ymd") == dt.date(2024, 4, 16)
    assert parse_date("cm_pv_2023_décembre_5", year_first, "ymd") == dt.date(2023, 12, 5)
    assert parse_date("cm_pv_2023_brumaire_5", year_first, "ymd") is None  # not a month name
    assert parse_date("PV 14.03.2024", r"(\d{2})\.(\d{2})\.(\d{4})") == dt.date(2024, 3, 14)


def test_prefer_context_date_ranks_the_configured_regex_then_the_row_then_url_shapes():
    import datetime as dt

    html = (
        "<table><tr><td>04.12.2023</td>"
        "<td><a href='/documents/20231207_Extrait_PV_CC_04122023_1.pdf'>Extrait</a></td>"
        "<td><a href='/documents/20231220_PV_CC_18122023_2.pdf'>Procès-verbal</a></td>"
        "<td><a href='/documents/20231210_PV_3.pdf'>Procès-verbal</a></td></tr></table>"
    )
    step = AdapterStep(selector="a", context="row", prefer_context_date=True)
    links = HtmlLinksAdapter().extract_links(
        html, "https://example.ch/pv", step, r"_CC_(\d{2})(\d{2})(\d{4})", "dmy"
    )
    assert [link.date for link in links] == [
        dt.date(2023, 12, 4),  # session date in the file name
        dt.date(2023, 12, 18),  # the file name corrects a row that groups two sessions
        dt.date(2023, 12, 4),  # no session date in the name: the row, not the upload prefix
    ]
