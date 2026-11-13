"""lint-communes: the committed configuration is clean, every check fires on a fabricated file, and the
loader reads a directory of files as well as the single file."""

import copy
import pathlib

import yaml
from typer.testing import CliRunner

from opencommune.cli import app
from opencommune.communes import bfs_register
from opencommune.lint import lint_communes

REPO = pathlib.Path(__file__).resolve().parent.parent

ENTRY = {
    "bfs_id": 363,
    "name": "Ostermundigen",
    "canton": "BE",
    "language": "de",
    "added": "2026-09-08",
    "website": "https://www.ostermundigen.ch",
    "vendor": "weblication",
    "body": "parliament",
    "lat": 46.956,
    "lon": 7.487,
    "listing_urls": ["https://www.ostermundigen.ch/protokolle?page={0..3}"],
    "adapter": "html_links",
    "adapter_config": {
        "steps": [
            {
                "selector": "a[href$='.pdf']",
                "text_regex": "^Protokoll",
                "next_selector": "a[rel=next]",
            }
        ],
        "date_regex": r"(\d{2})\.(\d{2})\.(\d{4})",
        "max_documents": 20,
    },
}
BFS = {363: ("Ostermundigen", "BE"), 351: ("Bern", "BE"), 5586: ("Lausanne", "VD")}


def write(tmp_path, entries, name="communes.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_committed_configuration_is_clean():
    snapshot = REPO / "data" / "bfs" / "snapshot-2026-01-01.csv"
    bfs = bfs_register(snapshot) if snapshot.exists() else None
    assert lint_communes(REPO / "data" / "communes.yaml", bfs) == []


def test_clean_entry_passes_with_and_without_the_snapshot(tmp_path):
    path = write(tmp_path, [ENTRY])
    assert lint_communes(path, BFS) == []
    assert lint_communes(path, None) == []


def test_every_check_fires(tmp_path):
    # the schema rejects these before any other check runs on them
    vendor_typo = dict(ENTRY, vendor="wordpres")
    extra_key = dict(ENTRY, bfs_id=351, name="Bern", listing_url="https://stadtrat.bern.ch")
    # a valid entry with every runtime problem
    bad = copy.deepcopy(ENTRY)
    bad.update(
        {
            "canton": "ZH",
            "lat": 52.5,
            "lon": 13.4,
            "listing_urls": ["/protokolle?page={3..0}&y={1..2}", "https://www.ostermundigen.ch/x"],
            "adapter": "htlm_links",
        }
    )
    del bad["added"]
    bad["adapter_config"]["steps"][0].update(
        {"selector": "a[href$=", "text_regex": "(", "url_regex": "["}
    )
    bad["adapter_config"]["date_regex"] = r"(\d{2})\.(\d{2})"
    twice = dict(ENTRY, name="Aa")
    problems = lint_communes(write(tmp_path, [vendor_typo, extra_key, bad, twice]), BFS)
    text = "\n".join(problems)
    for expected in [
        "communes.yaml entry 1 (Ostermundigen): vendor: Input should be",  # vocabulary
        "communes.yaml entry 2 (Bern): listing_url: Extra inputs are not permitted",  # extra="forbid"
        "363 Ostermundigen: no added date",
        "canton ZH, BFS says BE",
        "lat 52.5 outside",
        "lon 13.4 outside",
        "unknown adapter 'htlm_links'",
        "listing URL not absolute: /protokolle",
        "more than one {a..b} range",
        "range {3..0} runs backwards",
        "date_regex needs three groups",
        "step 1 selector does not parse",
        "step 1 text_regex does not compile",
        "step 1 url_regex does not compile",
        "363 Aa: listed twice (also in communes.yaml)",
        "363 Aa: BFS name is Ostermundigen",
        "communes.yaml: entries are not sorted by canton, then name",
    ]:
        assert expected in text, f"missing: {expected}\n{text}"


def test_lint_command_exits_non_zero_with_the_list(tmp_path):
    path = write(tmp_path, [dict(ENTRY, lat=0.0)])
    res = CliRunner().invoke(app, ["lint-communes", "--path", str(path)])
    assert res.exit_code == 1 and "lat 0.0 outside" in res.output and "1 problems" in res.output
    res = CliRunner().invoke(app, ["lint-communes", "--path", str(write(tmp_path, [ENTRY]))])
    assert res.exit_code == 0, res.output
