"""Build the static map asset from the swiss-maps TopoJSON (BSD-licensed package of the FSO's
generalised boundaries, which derive from swisstopo swissBOUNDARIES3D).

Usage: uv run python scripts/build_map.py path/to/swiss-maps/2026/ch-combined.json
The input is the 2026 layer of the npm package swiss-maps 4.7.0: communes and cantons as on
1 January 2026. Writes frontend/src/lib/ch-map.json with projected SVG paths for cantons, lakes and
municipalities keyed by BFS id, plus the projection so points can be placed at runtime.

1. The projection is fixed (BOUNDS), so a newer boundary year does not move the map.
2. Each arc is simplified once (Douglas-Peucker, TOLERANCE map units) before the rings are put
   together, so neighbouring shapes keep the same border. A ring that would lose half its area
   keeps its arcs unsimplified.
3. Only communes of the register (data/register/) are kept. Areas that belong to no commune (the
   Staatswald Galm, the Kommunanzen in Ticino) are left out; the canton layer draws the land there.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from opencommune.register import load_register

OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "ch-map.json"
SOURCE = (
    "swiss-maps 4.7.0, layer 2026 (FSO generalised boundaries from swisstopo swissBOUNDARIES3D,"
    " as on 1 January 2026), https://github.com/interactivethings/swiss-maps"
)
WIDTH = 900.0
# lon0, lon1, lat0, lat1: the extent of the first map (swiss-maps layer 2021), kept since
BOUNDS = (5.956800664952974, 10.493446773955753, 45.72493187952227, 47.81828989575225)
TOLERANCE = 0.5  # map units: half a pixel on the 900-pixel map
# canton abbreviations in the order of their numbers, the ids of the canton layer
CANTONS = ["ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "FR", "SO", "BS", "BL"]
CANTONS += ["SH", "AR", "AI", "SG", "GR", "AG", "TG", "TI", "VD", "VS", "NE", "GE", "JU"]

Point = tuple[float, float]


def decode_arcs(topo: dict) -> list[list[Point]]:
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


def ring_coords(ring: list[int], arcs: list) -> list[Point]:
    out: list[Point] = []
    for idx in ring:
        pts = arcs[~idx][::-1] if idx < 0 else arcs[idx]
        if out and out[-1] == pts[0]:
            pts = pts[1:]
        out.extend(pts)
    return out


def geometry_arc_rings(geom: dict) -> list[list[int]]:
    if geom["type"] == "Polygon":
        return geom["arcs"]
    if geom["type"] == "MultiPolygon":
        return [r for poly in geom["arcs"] for r in poly]
    return []


def geometry_rings(geom: dict, arcs: list) -> list[list[Point]]:
    return [ring_coords(r, arcs) for r in geometry_arc_rings(geom)]


class Projection:
    """Plate carree with latitude correction; Switzerland is small enough for that."""

    def __init__(self, lon0: float, lon1: float, lat0: float, lat1: float, width: float) -> None:
        self.lon0, self.lat1 = lon0, lat1
        self.cos = math.cos(math.radians((lat0 + lat1) / 2))
        self.k = width / ((lon1 - lon0) * self.cos)
        self.width = width
        self.height = (lat1 - lat0) * self.k

    def __call__(self, lon: float, lat: float) -> Point:
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


def simplify(pts: list[Point], tolerance: float) -> list[Point]:
    """Douglas-Peucker. The end points stay, so arcs still meet; a closed arc keeps its farthest
    point as well."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = pts[i], pts[j]
        dx, dy = x2 - x1, y2 - y1
        n = math.hypot(dx, dy)
        best, dmax = 0, tolerance
        for m in range(i + 1, j):
            x, y = pts[m]
            d = abs(dy * (x - x1) - dx * (y - y1)) / n if n else math.hypot(x - x1, y - y1)
            if d > dmax:
                best, dmax = m, d
        if best:
            keep[best] = True
            stack += [(i, best), (best, j)]
    return [p for p, k in zip(pts, keep, strict=True) if k]


def area(ring: list[Point]) -> float:
    pairs = zip(ring, ring[1:] + ring[:1], strict=True)
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in pairs)) / 2


def path_d(rings: list[list[Point]]) -> str:
    """Rings in map units to SVG path data at 0.1 units; repeated points are dropped."""
    parts = []
    for ring in rings:
        pts: list[str] = []
        for x, y in ring:
            p = f"{x:.1f} {y:.1f}"
            if not pts or pts[-1] != p:
                pts.append(p)
        if len(pts) > 1 and pts[-1] == pts[0]:
            pts.pop()
        parts.append("M" + "L".join(pts) + "Z")
    return "".join(parts)


def point_in_rings(rings: list[list[Point]], x: float, y: float) -> bool:
    inside = False
    for ring in rings:
        for i in range(len(ring)):
            (x1, y1), (x2, y2) = ring[i], ring[(i + 1) % len(ring)]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
                inside = not inside
    return inside


def main(src: Path) -> None:
    topo = json.loads(src.read_text())
    proj = Projection(*BOUNDS, WIDTH)
    full = [[proj(lon, lat) for lon, lat in arc] for arc in decode_arcs(topo)]
    arcs = [simplify(arc, TOLERANCE) for arc in full]

    cantons = topo["objects"]["cantons"]["geometries"]
    municipalities = topo["objects"]["municipalities"]["geometries"]
    lakes = topo["objects"]["lakes"]["geometries"]

    restored = 0
    for g in cantons + municipalities + lakes:
        for ring in geometry_arc_rings(g):
            if area(ring_coords(ring, arcs)) < area(ring_coords(ring, full)) / 2:
                for idx in ring:
                    a = ~idx if idx < 0 else idx
                    restored += arcs[a] is not full[a]
                    arcs[a] = full[a]
    print(
        f"points: {sum(map(len, full))} -> {sum(map(len, arcs))}, {restored} arcs kept unsimplified"
    )

    communes = {e.bfs_id: e for e in load_register()}
    shapes = {g["id"]: g for g in municipalities}
    print("not communes, left out:", sorted(set(shapes) - set(communes)))
    print("communes of the register without a shape:", sorted(set(communes) - set(shapes)))

    checks = {
        261: (8.5417, 47.3769),  # Zürich
        5002: (9.0230, 46.1950),  # Bellinzona
        5590: (6.6620, 46.5100),  # Pully
        355: (7.4145, 46.9245),  # Köniz
        6831: (7.3708, 47.2803),  # Moutier, canton JU since 2026
        5239: (8.8043, 46.0023),  # Tresa
        5656: (6.4260, 46.5655),  # Hautemorges
    }
    canton_rings = {g["id"]: geometry_rings(g, arcs) for g in cantons}
    for bfs, (lon, lat) in checks.items():
        x, y = proj(lon, lat)
        rings = geometry_rings(shapes[bfs], arcs) if bfs in shapes else None
        canton = communes[bfs].canton if bfs in communes else None
        in_canton = canton in CANTONS and point_in_rings(
            canton_rings[CANTONS.index(canton) + 1], x, y
        )
        print(
            f"  bfs {bfs}: polygon present={rings is not None}"
            f" contains point={point_in_rings(rings, x, y) if rings else None}"
            f" in canton {canton}={in_canton}"
        )

    asset = {
        "source": SOURCE,
        "projection": proj.as_dict(),
        "cantons": [{"id": g.get("id"), "d": path_d(geometry_rings(g, arcs))} for g in cantons],
        "lakes": [path_d(geometry_rings(g, arcs)) for g in lakes],
        "municipalities": {
            str(g["id"]): path_d(geometry_rings(g, arcs))
            for g in municipalities
            if g["id"] in communes
        },
    }
    OUT.write_text(json.dumps(asset, separators=(",", ":")))
    print(
        f"wrote {OUT} ({OUT.stat().st_size // 1024} KB), {len(asset['cantons'])} cantons, {len(asset['municipalities'])} municipalities, {len(asset['lakes'])} lakes, viewBox 0 0 {proj.width:.0f} {proj.height:.0f}"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
