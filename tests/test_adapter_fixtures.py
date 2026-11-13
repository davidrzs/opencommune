"""Recorded-page fixtures, one directory per case: tests/fixtures/<adapter>/<case>/.

Each case holds the page as `input.<ext>` (trimmed to the relevant part of a real listing page, with
the source URL and recording date in a leading comment), the call parameters in `step.json`
(`base_url`, `step`, optional `date_regex`, `date_order`, `parent`, `headers`) and the expected
result in `expected.json` (`links`, optional `count` when only a prefix of the links is listed,
optional `next_url`). The adapter is the directory name.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from opencommune.crawl.adapters import Link, get_adapter
from opencommune.schemas import AdapterStep

FIX = pathlib.Path(__file__).parent / "fixtures"
CASES = sorted(FIX.glob("*/*/step.json"))


def _link_dict(link: Link) -> dict:
    out: dict = {
        "url": link.url,
        "text": link.text,
        "date": link.date.isoformat() if link.date else None,
    }
    if link.date_precision != "day":
        out["date_precision"] = link.date_precision
    if link.context_date is not None:
        out["context_date"] = link.context_date.isoformat()
    if link.upstream_id is not None:
        out["upstream_id"] = link.upstream_id
    return out


def _parent(raw: dict | None) -> Link | None:
    if not raw:
        return None
    date = dt.date.fromisoformat(raw["date"]) if raw.get("date") else None
    return Link(
        url=raw["url"],
        text=raw.get("text", ""),
        date=date,
        date_precision=raw.get("date_precision", "day"),
    )


def run_case(case_dir: pathlib.Path) -> tuple[list[dict], str | None, dict, dict]:
    adapter = get_adapter(case_dir.parent.name)
    params = json.loads((case_dir / "step.json").read_text(encoding="utf-8"))
    content = next(case_dir.glob("input.*")).read_bytes()
    text = content.decode("utf-8", errors="replace")
    step = AdapterStep(**params["step"])
    links = adapter.extract_links(
        text,
        params["base_url"],
        step,
        params.get("date_regex"),
        params.get("date_order", "dmy"),
        parent=_parent(params.get("parent")),
    )
    next_url = adapter.next_url(text, params["base_url"], step, headers=params.get("headers"))
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    return [_link_dict(link) for link in links], next_url, expected, params


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{p.parent.parent.name}/{p.parent.name}" for p in CASES]
)
def test_recorded_page(case: pathlib.Path):
    got, next_url, expected, _ = run_case(case.parent)
    assert len(got) == expected.get("count", len(expected["links"]))
    assert got[: len(expected["links"])] == expected["links"]
    assert next_url == expected.get("next_url")
