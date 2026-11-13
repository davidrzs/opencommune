"""Build the static map asset from the swiss-maps TopoJSON (swisstopo data, BSD-licensed package).

Usage: uv run python scripts/build_map.py path/to/ch-combined.json
Writes frontend/src/lib/ch-map.json with projected SVG paths for cantons, lakes and
municipalities keyed by BFS id, plus the projection so points can be placed at runtime.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "ch-map.json"
WIDTH = 900.0


def decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def ring_coords(ring: list[int], arcs: list) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for idx in ring:
        pts = arcs[~idx][::-1] if idx < 0 else arcs[idx]
        if out and out[-1] == pts[0]:
            pts = pts[1:]
        out.extend(pts)
    return out


def geometry_rings(geom: dict, arcs: list) -> list[list[tuple[float, float]]]:
    if geom["type"] == "Polygon":
        return [ring_coords(r, arcs) for r in geom["arcs"]]
    if geom["type"] == "MultiPolygon":
        return [ring_coords(r, arcs) for poly in geom["arcs"] for r in poly]
    return []


class Projection:
    """Plate carree with latitude correction; Switzerland is small enough for that."""

    def __init__(self, lon0: float, lon1: float, lat0: float, lat1: float, width: float) -> None:
        self.lon0, self.lat1 = lon0, lat1
        self.cos = math.cos(math.radians((lat0 + lat1) / 2))
        self.k = width / ((lon1 - lon0) * self.cos)
        self.width = width
        self.height = (lat1 - lat0) * self.k

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        return ((lon - self.lon0) * self.cos * self.k, (self.lat1 - lat) * self.k)

    def as_dict(self) -> dict:
        return {
            "lon0": self.lon0,
            "lat1": self.lat1,
            "cos": self.cos,
            "k": self.k,
            "width": round(self.width, 1),
            "height": round(self.height, 1),
        }


def path_d(rings: list[list[tuple[float, float]]], proj: Projection) -> str:
    parts = []
    for ring in rings:
        pts = [proj(lon, lat) for lon, lat in ring]
        parts.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z")
    return "".join(parts)


def point_in_rings(rings: list[list[tuple[float, float]]], lon: float, lat: float) -> bool:
    inside = False
    for ring in rings:
        for i in range(len(ring)):
            (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1 + 1e-12) + x1:
                inside = not inside
    return inside


def main(src: Path) -> None:
    topo = json.loads(src.read_text())
    arcs = decode_arcs(topo)
    lons = [p[0] for a in arcs for p in a]
    lats = [p[1] for a in arcs for p in a]
    proj = Projection(min(lons), max(lons), min(lats), max(lats), WIDTH)

    cantons = topo["objects"]["cantons"]["geometries"]
    municipalities = topo["objects"]["municipalities"]["geometries"]
    lakes = topo["objects"]["lakes"]["geometries"]
    print(
        "ids on cantons:",
        [g.get("id") for g in cantons[:5]],
        "| municipalities:",
        [g.get("id") for g in municipalities[:5]],
    )

    checks = {
        261: (8.5417, 47.3769),
        5002: (9.0230, 46.1950),
        5590: (6.6620, 46.5100),
        355: (7.4145, 46.9245),
    }
    muni_rings = {g.get("id"): geometry_rings(g, arcs) for g in municipalities}
    for bfs, (lon, lat) in checks.items():
        rings = muni_rings.get(bfs)
        print(
            f"  bfs {bfs}: polygon present={rings is not None} contains point={point_in_rings(rings, lon, lat) if rings else None}"
        )

    asset = {
        "source": "swiss-maps 4.7.0 (swisstopo swissBOUNDARIES3D 2021), https://github.com/interactivethings/swiss-maps",
        "projection": proj.as_dict(),
        "cantons": [
            {"id": g.get("id"), "d": path_d(geometry_rings(g, arcs), proj)} for g in cantons
        ],
        "lakes": [path_d(geometry_rings(g, arcs), proj) for g in lakes],
        "municipalities": {
            str(g.get("id")): path_d(geometry_rings(g, arcs), proj) for g in municipalities
        },
    }
    OUT.write_text(json.dumps(asset, separators=(",", ":")))
    print(
        f"wrote {OUT} ({OUT.stat().st_size // 1024} KB), {len(asset['cantons'])} cantons, {len(asset['municipalities'])} municipalities, {len(asset['lakes'])} lakes, viewBox 0 0 {proj.width:.0f} {proj.height:.0f}"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
