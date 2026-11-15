import pytest

from opencommune import build, scope
from tests.scope_data import A, D, serving_db, text_db


@pytest.mark.parametrize(
    ("text", "joined"),
    [
        ("Gemeinde-\nrat", "Gemeinderat"),
        ("Ver-\nwal-\ntung", "Verwaltung"),
        ("Abstim-\nmung über die Vor-\nlage", "Abstimmung über die Vorlage"),
        ("Gebüh-\nren und Ä-\nnderung", "Gebühren und Änderung"),
        ("crédit d'enga-\ngement", "crédit d'engagement"),
        ("é-\nécole", "éécole"),
        # an upper-case continuation is a new word: a compound or a name
        ("Gemeinde-\nRat", "Gemeinde-\nRat"),
        ("Gemeinde-\nÄmter", "Gemeinde-\nÄmter"),
        # no letter on either side, or not exactly a hyphen and one line break
        ("2025-\n2026", "2025-\n2026"),
        ("Budget-\n2026", "Budget-\n2026"),
        ("Seite 3 -\nweiter", "Seite 3 -\nweiter"),
        ("-\nrat", "-\nrat"),
        ("Gemeinde-\n", "Gemeinde-\n"),
        ("Gemeinde- \nrat", "Gemeinde- \nrat"),
        ("Gemeinde-\n\nrat", "Gemeinde-\n\nrat"),
        ("Gemeinde–\nrat", "Gemeinde–\nrat"),
        ("Gemeinde-rat", "Gemeinde-rat"),
        # a hyphen before und, oder, bis, bzw or sowie shortens a compound
        ("Ein-\nund Ausgaben", "Ein-\nund Ausgaben"),
        ("Hoch-\noder Tiefbau", "Hoch-\noder Tiefbau"),
        ("Primar-\nbzw. Sekundarschule", "Primar-\nbzw. Sekundarschule"),
        ("Gemeinde-\nunderlage", "Gemeindeunderlage"),
    ],
)
def test_words_split_at_a_line_end_are_joined(text, joined):
    assert scope.join_split_words(text) == joined


def test_the_types_are_those_of_deliberation_money_and_proposals():
    families = {"deliberation", "money", "proposals"}
    assert set(scope.TYPES) == {t for t, f in build.FAMILIES.items() if f in families}


def test_pages_lists_every_page_in_scope_with_its_text(tmp_path):
    serving = serving_db(tmp_path / "serving.db")
    text = text_db(tmp_path / "text.db")
    pages = list(scope.pages(serving, text))
    assert [(p.sha256, p.page, p.types, p.source, p.usable) for p in pages] == [
        (A, 1, ("budget",), "ocr", True),
        (A, 2, ("budget", "minutes"), "layer", True),
        (A, 3, ("minutes",), "layer", False),
        (A, 6, ("proposal",), "layer", True),
        (A, 7, ("proposal",), None, False),
        (D, 1, ("decisions",), "layer", True),
    ]
    assert pages[1].text == "Der Gemeinderat beschliesst den Steuerfuss.\nGemeinde-\nRat"
    assert pages[1].raw.startswith("Der Gemeinde-\nrat") and pages[4].text == ""
