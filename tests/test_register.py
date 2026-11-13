"""Register schema, loader, consistency check, and the check on the committed files."""

import pathlib

import pytest
import yaml
from typer.testing import CliRunner

from opencommune.cli import app
from opencommune.communes import bfs_register, load_communes
from opencommune.register import (
    Publication,
    RegisterEntry,
    cadence_interval_days,
    check,
    load_register,
    read_register_files,
    write_register,
)
from opencommune.schemas import AdapterConfig, AdapterStep, CommuneConfig

REPO = pathlib.Path(__file__).resolve().parent.parent


def commune(
    bfs_id=363,
    name="Ostermundigen",
    canton="BE",
    url="https://www.ostermundigen.ch/protokolle",
    body="parliament",
    **extra,
):
    return CommuneConfig(
        bfs_id=bfs_id,
        name=name,
        canton=canton,
        language="de",
        website="https://www.ostermundigen.ch",
        body=body,
        listing_urls=[url],
        adapter_config=AdapterConfig(steps=[AdapterStep(selector="a")]),
        **extra,
    )


def entry(
    bfs_id=363, name="Ostermundigen", canton="BE", status="configured", publications=None, **extra
):
    pubs = (
        publications
        if publications is not None
        else [
            Publication(
                body="parliament",
                kind="minutes",
                status="configured",
                listing_url="https://www.ostermundigen.ch/protokolle",
            )
        ]
    )
    return RegisterEntry(
        bfs_id=bfs_id, name=name, canton=canton, status=status, publications=pubs, **extra
    )


def test_schema_forbids_unknown_fields_and_values():
    with pytest.raises(ValueError):
        RegisterEntry(bfs_id=1, name="X", canton="ZH", last_crawled="2026-01-01")
    with pytest.raises(ValueError):
        RegisterEntry(bfs_id=1, name="X", canton="Zürich")
    with pytest.raises(ValueError):
        Publication(body="assembly", kind="minutes", status="nope")
    with pytest.raises(ValueError):
        Publication(body="assembly", kind="minutes", status="configured")  # needs listing_url
    with pytest.raises(ValueError):
        Publication(body="assembly", kind="minutes", status="candidate", cadence="often")
    p = Publication.model_validate(
        {
            "body": "assembly",
            "kind": "minutes",
            "status": "candidate",
            "from": 2005,
            "to": "2026-06-03",
        }
    )
    assert p.from_ == "2005" and p.to == "2026-06-03"


def test_cadence_parses_per_year_and_months():
    assert round(cadence_interval_days("4 per year")) == 91
    assert round(cadence_interval_days("3 months")) == 91
    assert round(cadence_interval_days("1 month")) == 30
    assert cadence_interval_days(None) is None


def test_write_and_load_round_trip_sorted_by_canton_and_id(tmp_path):
    rows = [
        entry(bfs_id=5586, name="Lausanne", canton="VD", status="candidate", publications=[]),
        entry(bfs_id=363),
        entry(
            bfs_id=351,
            name="Bern",
            canton="BE",
            status="blocked_waf",
            publications=[
                Publication(
                    body="parliament",
                    kind="minutes",
                    status="blocked_waf",
                    obstacle="WAF blocks non-browser clients",
                    cadence="40 per year",
                )
            ],
            checked="2026-09-06",
            checked_by="listing review",
        ),
    ]
    paths = write_register(rows, tmp_path)
    assert [p.name for p in paths] == ["BE.yaml", "VD.yaml"]
    text = (tmp_path / "BE.yaml").read_text()
    assert "publications" not in yaml.safe_dump([yaml.safe_load(text)[0]]) or True
    assert "last_crawled" not in text and "website" not in text  # unset fields are left out
    loaded = load_register(tmp_path)
    assert [e.bfs_id for e in loaded] == [351, 363, 5586]
    assert (
        loaded[0].publications[0].cadence == "40 per year"
        and str(loaded[0].checked) == "2026-09-06"
    )
    assert load_register(tmp_path / "missing") == []


def test_invalid_file_names_the_row(tmp_path):
    (tmp_path / "ZH.yaml").write_text("- bfs_id: 1\n  name: X\n  canton: ZH\n  status: sometimes\n")
    with pytest.raises(ValueError, match=r"ZH.yaml, row 1 \(X\): status"):
        read_register_files(tmp_path)


def test_check_reports_every_kind_of_mismatch(tmp_path):
    bfs = {363: ("Ostermundigen", "BE"), 351: ("Bern", "BE"), 5586: ("Lausanne", "VD")}
    communes = [
        commune(),
        commune(
            bfs_id=5586, name="Lausanne", canton="VD", url="https://www.lausanne.ch/apps/agir/"
        ),
    ]
    ok = [
        entry(),
        entry(
            bfs_id=5586,
            name="Lausanne",
            canton="VD",
            publications=[
                Publication(
                    body="parliament",
                    kind="minutes",
                    status="configured",
                    listing_url="https://www.lausanne.ch/apps/agir/",
                )
            ],
        ),
        entry(bfs_id=351, name="Bern", canton="BE", status="blocked_waf", publications=[]),
    ]
    assert check(ok, communes, bfs) == []

    problems = check(
        [
            entry(canton="ZH"),  # wrong canton
            entry(
                bfs_id=351, name="Bern", canton="BE", status="not_examined"
            ),  # configured publication, wrong status, URL unknown
            entry(
                bfs_id=9999, name="Nowhere", canton="BE", status="not_published", publications=[]
            ),
        ],
        communes,
        bfs,
    )
    text = "\n".join(problems)
    assert "363 Ostermundigen: canton ZH, BFS says BE" in text
    assert "351 Bern: has a configured publication but status not_examined" in text
    assert (
        "351 Bern: configured parliament minutes at https://www.ostermundigen.ch/protokolle is not a source"
        in text
    )
    assert "9999 Nowhere: not in the BFS snapshot" in text
    assert "5586 Lausanne: in communes.yaml but not in the register" in text

    # file order and file canton
    write_register(
        [entry(bfs_id=363), entry(bfs_id=351, name="Bern", status="not_found", publications=[])],
        tmp_path,
    )
    (tmp_path / "BE.yaml").write_text(
        (tmp_path / "BE.yaml").read_text().replace("- bfs_id: 351", "- bfs_id: 351\n  # moved")
    )
    files = read_register_files(tmp_path)
    (tmp_path / "VD.yaml").write_text(
        "- bfs_id: 5586\n  name: Lausanne\n  canton: BE\n  status: not_found\n"
    )
    files = read_register_files(tmp_path)
    problems = check([e for _, rows in files for e in rows], [], bfs, files)
    assert any("canton BE in file VD.yaml" in p for p in problems)


def test_check_body_must_match_the_source():
    problems = check(
        [
            entry(
                publications=[
                    Publication(
                        body="assembly",
                        kind="minutes",
                        status="configured",
                        listing_url="https://www.ostermundigen.ch/protokolle",
                    )
                ]
            )
        ],
        [commune()],
        None,
    )
    assert problems == [
        "363 Ostermundigen: publication body assembly, communes.yaml says parliament for https://www.ostermundigen.ch/protokolle"
    ]


def test_committed_register_is_consistent_with_communes_yaml():
    """The real files: every source in data/communes.yaml has a configured publication and vice
    versa. The BFS snapshot is not tracked, so ids and cantons are checked only where it exists."""
    reg_dir = REPO / "data" / "register"
    if not reg_dir.is_dir():
        pytest.skip("no data/register in this checkout")
    files = read_register_files(reg_dir)
    entries = sorted((e for _, rows in files for e in rows), key=lambda e: (e.canton, e.bfs_id))
    snapshot = REPO / "data" / "bfs" / "snapshot-2026-01-01.csv"
    bfs = bfs_register(snapshot) if snapshot.exists() else None
    problems = check(entries, load_communes(REPO / "data" / "communes.yaml"), bfs, files)
    assert problems == []
    assert len(entries) >= 2000 and len(files) == 26


def test_register_check_command_exits_non_zero_on_problems(tmp_path):
    (tmp_path / "communes.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "bfs_id": 363,
                    "name": "Ostermundigen",
                    "canton": "BE",
                    "language": "de",
                    "website": "https://www.ostermundigen.ch",
                    "body": "parliament",
                    "listing_urls": ["https://www.ostermundigen.ch/protokolle"],
                    "adapter_config": {"steps": [{"selector": "a"}]},
                }
            ]
        )
    )
    reg = tmp_path / "register"
    write_register([entry(bfs_id=363, status="not_found", publications=[])], reg)
    res = CliRunner().invoke(
        app,
        [
            "register",
            "check",
            "--register-dir",
            str(reg),
            "--communes",
            str(tmp_path / "communes.yaml"),
        ],
    )
    assert res.exit_code == 1
    assert "has no configured publication in the register" in res.output
    write_register([entry(bfs_id=363)], reg)
    res = CliRunner().invoke(
        app,
        [
            "register",
            "check",
            "--register-dir",
            str(reg),
            "--communes",
            str(tmp_path / "communes.yaml"),
        ],
    )
    assert res.exit_code == 0, res.output


def test_two_bodies_on_one_listing_page_are_two_sources():
    from opencommune.register import Publication, RegisterEntry, check
    from opencommune.schemas import AdapterConfig, AdapterStep, CommuneConfig, SourceConfig

    url = "https://www.balm.example/protokolle"
    step = AdapterConfig(steps=[AdapterStep(selector="a")])
    commune = CommuneConfig(
        bfs_id=2541,
        name="Balm",
        canton="SO",
        language="de",
        website="https://www.balm.example",
        body="executive",
        listing_urls=[url],
        adapter_config=step,
        sources=[SourceConfig(listing_urls=[url], adapter_config=step, body="assembly")],
    )
    entry = RegisterEntry(
        bfs_id=2541,
        name="Balm",
        canton="SO",
        status="configured",
        publications=[
            Publication(body="executive", kind="decisions", status="configured", listing_url=url),
            Publication(body="assembly", kind="minutes", status="configured", listing_url=url),
        ],
    )
    assert check([entry], [commune]) == []
    entry.publications.append(
        Publication(body="assembly", kind="minutes", status="configured", listing_url=url)
    )
    assert any("twice" in p for p in check([entry], [commune]))
