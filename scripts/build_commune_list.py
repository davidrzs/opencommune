"""Build data/bfs/communes_all.json: every commune of the BFS snapshot with its website and population.

Input: the BFS snapshot in data/bfs/ (`opencommune bfs-sync`). One SPARQL query to Wikidata for the
municipalities of Switzerland (P31 Q70208) with BFS number (P771), official website (P856) and
population (P1082, the newest statement), sent with the crawler's User-Agent. Only ids that are in
the snapshot are kept, so former municipalities drop out. Output rows {bfs, name, canton, website,
pop}, newest population first, as scripts/probe_vendors.py and scripts/probe_iweb.py read them;
a commune without a website in Wikidata keeps website null.

Usage: uv run python scripts/build_commune_list.py [out.json]   (default data/bfs/communes_all.json)
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import httpx

from opencommune.communes import bfs_register
from opencommune.config import settings

SPARQL = "https://query.wikidata.org/sparql"
QUERY = """
SELECT ?bfs ?website ?pop ?when WHERE {
  ?item wdt:P31 wd:Q70208 ; wdt:P771 ?bfs .
  OPTIONAL { ?item wdt:P856 ?website . }
  OPTIONAL { ?item p:P1082 ?ps . ?ps ps:P1082 ?pop . OPTIONAL { ?ps pq:P585 ?when . } }
}
"""


def query_wikidata() -> list[dict]:
    headers = {"User-Agent": settings.ua, "Accept": "application/sparql-results+json"}
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0), headers=headers) as client:
        r = client.get(SPARQL, params={"query": QUERY, "format": "json"})
        r.raise_for_status()
    return r.json()["results"]["bindings"]


def main(out: Path) -> None:
    snapshot = bfs_register()
    if not snapshot:
        sys.exit("BFS snapshot missing; run `opencommune bfs-sync` first")
    rows: dict[int, dict] = {
        bfs: {
            "bfs": bfs,
            "name": name.split(" (")[0],
            "canton": canton,
            "website": None,
            "pop": 0,
            "_when": "",
        }
        for bfs, (name, canton) in snapshot.items()
    }
    for b in query_wikidata():
        try:
            bfs = int(b["bfs"]["value"])
        except (KeyError, ValueError):
            continue
        row = rows.get(bfs)
        if row is None:
            continue
        website = b.get("website", {}).get("value")
        if website and (row["website"] is None or website.startswith("https://")):
            row["website"] = website
        when = b.get("when", {}).get("value", "")
        if "pop" in b and when >= row["_when"]:
            with contextlib.suppress(ValueError):
                row["pop"], row["_when"] = int(float(b["pop"]["value"])), when
    out_rows = sorted(rows.values(), key=lambda r: -r["pop"])
    for r in out_rows:
        del r["_when"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    with_site = sum(1 for r in out_rows if r["website"])
    print(f"wrote {out}: {len(out_rows)} communes, {with_site} with a website")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else settings.bfs_dir / "communes_all.json")
