"""Load the hand-curated commune list and the BFS commune register snapshot."""

from __future__ import annotations

import csv
import io
from functools import lru_cache
from pathlib import Path

import yaml

from .config import settings
from .schemas import CommuneConfig

BFS_SNAPSHOT_URL = "https://www.agvchapp.bfs.admin.ch/api/communes/snapshot?date=01-01-2026"
BFS_SNAPSHOT_FILE = "snapshot-2026-01-01.csv"


def load_cantons(path: Path | None = None) -> dict[str, dict]:
    p = path or settings.cantons_file
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def commune_files(path: Path | None = None) -> list[Path]:
    """The configuration file: `data/communes.yaml`, or the file given."""
    return [path or settings.communes_file]


def read_commune_items(path: Path | None = None) -> list[tuple[Path, list]]:
    """The raw entries of every configuration file, in file order, before validation."""
    out = []
    for file in commune_files(path):
        items = yaml.safe_load(file.read_text(encoding="utf-8")) or []
        if not isinstance(items, list):
            raise ValueError(f"{file}: expected a list of communes")
        out.append((file, items))
    return out


def load_communes(path: Path | None = None) -> list[CommuneConfig]:
    cantons = load_cantons()
    communes: list[CommuneConfig] = []
    for _, items in read_commune_items(path):
        for item in items:
            c = CommuneConfig.model_validate(item)
            regime = cantons.get(c.canton, {}).get(c.body)
            if regime and not c.publicity_regime:
                c.publicity_regime = regime
            communes.append(c)
    ids = [c.bfs_id for c in communes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate bfs_id in the commune configuration")
    return communes


def bfs_snapshot_path() -> Path:
    return settings.bfs_dir / BFS_SNAPSHOT_FILE


def ensure_bfs_snapshot(fetch_text) -> Path:
    """Download the register once. `fetch_text(url) -> str` is injected so this module has no HTTP."""
    p = bfs_snapshot_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(fetch_text(BFS_SNAPSHOT_URL), encoding="utf-8")
    return p


def _snapshot_rows(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    sample = text[:2000]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return [
        {k: (v or "").strip() for k, v in row.items()}
        for row in csv.DictReader(io.StringIO(text), delimiter=delimiter)
    ]


@lru_cache(maxsize=1)
def bfs_communes() -> dict[int, str]:
    """bfs_id -> official name for every commune (level 3) in the snapshot, or {} if not downloaded."""
    return {k: name for k, (name, _) in bfs_register().items()}


@lru_cache(maxsize=1)
def bfs_register(path: Path | None = None) -> dict[int, tuple[str, str]]:
    """bfs_id -> (official name, canton) for every commune in the snapshot, or {} if not downloaded.

    The snapshot lists cantons (level 1), districts (level 2) and communes (level 3); a commune's
    canton is the parent of its parent. Historical codes repeat across levels, so parents are
    looked up by (level, code)."""
    p = path or bfs_snapshot_path()
    if not p.exists():
        return {}
    rows = _snapshot_rows(p)
    by_level = {(r.get("Level"), r.get("HistoricalCode")): r for r in rows}
    out: dict[int, tuple[str, str]] = {}
    for r in rows:
        if r.get("Level") != "3" or not r.get("BfsCode", "").isdigit():
            continue
        district = by_level.get(("2", r.get("Parent")))
        canton = by_level.get(("1", district.get("Parent"))) if district else None
        out[int(r["BfsCode"])] = (r.get("Name", ""), canton.get("ShortName", "") if canton else "")
    return out
