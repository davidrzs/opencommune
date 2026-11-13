"""The committed commune configuration passes `opencommune lint-communes`: registered adapters,
absolute listing URLs, regexes that compile, selectors soupsieve parses, vocabularies and order. CI
also runs the command itself, with the BFS snapshot."""

import pathlib

from opencommune.communes import load_communes
from opencommune.lint import lint_communes

COMMUNES_FILE = pathlib.Path(__file__).parent.parent / "data" / "communes.yaml"


def test_the_committed_configuration_is_clean():
    assert lint_communes(COMMUNES_FILE) == []
    assert len(load_communes(COMMUNES_FILE)) > 100
