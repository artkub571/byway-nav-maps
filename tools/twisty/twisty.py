"""Finds Great Britain's twisty roads for the app's "Road fun" routing.

    python tools/twisty/twisty.py build --pbf <great-britain-latest.osm.pbf> --out <dir>

Runs in GitHub Actions (Actions → Twisty roads (GB)); needs osmium-tool.
Writes <dir>/twisty-gb.json.gz, stats.json and preview.png.

How (in the spirit of calimoto's "twisty roads" and Kurviger's curvy
routing, which favour long stretches of curves away from towns):
  1. Paved public roads from OpenStreetMap: trunk, primary, secondary,
     tertiary and unclassified (no motorways, private or unsurfaced ways).
  2. Ways are joined into continuous stretches: at a node where only two
     ways meet, or where one continuing way has the same ref / name.
  3. Every 10 m is weighted by how tight the bend is (curvature.py).
  4. Samples near a city (3 km), town (1.5 km) or village (500 m) don't
     count: those bends are junctions and streets, not riding.
  5. A stretch is twisty where the 1 km moving average weight is at least
     T_MIN (0.3, "winding"), for at least L_MIN (2 km); runs less than GAP
     (500 m) apart are joined.
The app routes "Road fun" legs through the best of these near the line.

Data: © OpenStreetMap contributors, ODbL (Geofabrik extract).
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import curvature as C  # noqa: E402

CLASSES = {"trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "unclassified": 1}
UNPAVED = {"unpaved", "gravel", "fine_gravel", "dirt", "earth", "ground", "grass", "mud", "sand", "compacted",
           "pebblestone", "woodchips", "rock", "stone", "grass_paver"}
PLACE_R = {"city": 3000.0, "town": 1500.0, "village": 500.0}
WINDOW = 1000.0  # m: moving average
T_MIN = 0.3      # 1 km average weight of a winding stretch (calimoto's "winding"; the app values
                 # each road by its own twistiness, so tight roads still win)
L_MIN = 2000.0   # m
GAP = 500.0      # m: twisty runs closer than this are one stretch
KNOWN = ["A537", "A57", "A542", "B3212", "A4069", "A4061", "A683", "B6270", "A686", "A939", "B4391", "A4086",
         "A6024", "B6277", "A39", "A470", "B3306"]


def run(cmd):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def extract(pbf: Path, work: Path):
    work.mkdir(parents=True, exist_ok=True)
    roads, places = work / "roads.pbf", work / "places.pbf"
    run(["osmium", "tags-filter", str(pbf), "w/highway=" + ",".join(CLASSES), "-o", str(roads), "--overwrite"])
    run(["osmium", "export", str(roads), "-f", "geojsonseq", "--geometry-types=linestring",
         "-x", "print_record_separator=false", "-o", str(work / "roads.jsonl"), "--overwrite"])
    run(["osmium", "tags-filter", str(pbf), "n/place=" + ",".join(PLACE_R), "-o", str(places), "--overwrite"])
    run(["osmium", "export", str(places), "-f", "geojsonseq", "--geometry-types=point",
         "-x", "print_record_separator=false", "-o", str(work / "places.jsonl"), "--overwrite"])
    return work / "roads.jsonl", work / "places.jsonl"


def load_ways(path: Path):
    ways, skipped = [], Counter()
    with path.open() as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            ft = json.loads(line)
            t = ft.get("properties") or {}
            hw = t.get("highway")
            if hw not in CLASSES:
                continue
            if t.get("area") == "yes" or t.get("access") in ("private", "no") \
                    or t.get("motor_vehicle") in ("private", "no") or t.get("motorcar") in ("private", "no"):
                skipped["no access"] += 1
                continue
            if t.get("surface") in UNPAVED:
                skipped["unpaved"] += 1
                continue
            c = (ft.get("geometry") or {}).get("coordinates") or []
            if len(c) < 2:
                continue
            ways.append((t.get("ref") or t.get("name") or "", CLASSES[hw], np.asarray(c, dtype=float)))
    print(f"ways: {len(ways)} kept, skipped {dict(skipped)}", flush=True)
    return ways


def load_places(path: Path):
    grid = defaultdict(list)
    n = 0
    with path.open() as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            ft = json.loads(line)
            r = PLACE_R.get((ft.get("properties") or {}).get("place"))
            if r is None:
                continue
            lon, lat = ft["geometry"]["coordinates"]
            grid[(int(math.floor(lon * 10)), int(math.floor(lat * 10)))].append((lon, lat, r))
            n += 1
    print(f"places: {n}", flush=True)
    return grid


def _pt(c):
    return (round(float(c[0]), 7), round(float(c[1]), 7))


def chains(ways):
    """Joins ways end to end into continuous stretches (lists of lon/lat)."""
    ends = defaultdict(list)
    for wi, (_, _, c) in enumerate(ways):
        ends[_pt(c[0])].append((wi, 0))
        ends[_pt(c[-1])].append((wi, 1))

    def partner(wi, e):
        pt = _pt(ways[wi][2][0 if e == 0 else -1])
        others = [o for o in ends[pt] if o[0] != wi]
        if len(others) == 1:
            return others[0]
        k = ways[wi][0]
        if k:
            same = [o for o in others if ways[o[0]][0] == k]
            if len(same) == 1:
                return same[0]
        return None

    def link(wi, e):
        p = partner(wi, e)
        return p if p is not None and partner(*p) == (wi, e) else None

    seen = set()
    for start in range(len(ways)):
        if start in seen:
            continue
        # Walk back to the chain's first way: (wi, e) = enter way wi at end e.
        wi, e = start, 0
        back = {start}
        while True:
            p = link(wi, e)
            if p is None or p[0] in back or p[0] in seen:
                break
            back.add(p[0])
            wi, e = p[0], 1 - p[1]
        # Walk forward from there.
        parts, keys, cls = [], Counter(), 0
        cur = (wi, e)
        while cur is not None and cur[0] not in seen:
            w, en = cur
            seen.add(w)
            c = ways[w][2] if en == 0 else ways[w][2][::-1]
            parts.append(c if not parts else c[1:])
            keys[ways[w][0]] += len(c)
            cls = max(cls, ways[w][1])
            nxt = link(w, 1 - en)
            cur = None if nxt is None else (nxt[0], nxt[1])
        coords = np.concatenate(parts) if len(parts) > 1 else parts[0]
        name = next((k for k, _ in keys.most_common() if k), "")
        yield name, cls, coords


def urban_mask(lonlat: np.ndarray, places) -> np.ndarray:
    lo, la = lonlat[:, 0], lonlat[:, 1]
    cands = []
    for gx in range(int(math.floor(lo.min() * 10)) - 1, int(math.floor(lo.max() * 10)) + 2):
        for gy in range(int(math.floor(la.min() * 10)) - 1, int(math.floor(la.max() * 10)) + 2):
            cands += places.get((gx, gy), [])
    mask = np.zeros(len(lonlat), dtype=bool)
    if not cands:
        return mask
    p = np.asarray(cands)
    k = 111320.0 * math.cos(math.radians(float(la.mean())))
    dx = (lo[:, None] - p[None, :, 0]) * k
    dy = (la[:, None] - p[None, :, 1]) * 110540.0
    return ((dx * dx + dy * dy) <= (p[None, :, 2] ** 2)).any(axis=1)


DIAG = {}  # known roads: how their chains scored (for tuning)


def stretches(name, cls, coords, places, out, hist):
    lat0 = float(coords[:, 1].mean())
    xy = C.to_metres(coords, lat0)
    seg = np.hypot(*np.diff(xy, axis=0).T)
    if seg.sum() < L_MIN:
        return
    s = C.resample(xy)
    w = C.weights_of(s)
    k = 111320.0 * math.cos(math.radians(lat0))
    lonlat = np.column_stack((s[:, 0] / k, s[:, 1] / 110540.0))
    urban = urban_mask(lonlat, places)
    n = int(WINDOW / C.STEP)
    ma = np.convolve(w, np.ones(n) / n, mode="same")
    rural = ~urban
    hist.append(ma[rural])
    if name in KNOWN:
        d = DIAG.setdefault(name, {"chains": 0, "km": 0.0, "max_ma": 0.0, "km_ma>=0.3": 0.0, "km_ma>=0.45": 0.0,
                                   "urban_km": 0.0})
        d["chains"] += 1
        d["km"] += len(w) * C.STEP / 1000
        d["max_ma"] = max(d["max_ma"], float(ma[rural].max()) if rural.any() else 0.0)
        d["km_ma>=0.3"] += float(((ma >= 0.3) & rural).sum()) * C.STEP / 1000
        d["km_ma>=0.45"] += float(((ma >= 0.45) & rural).sum()) * C.STEP / 1000
        d["urban_km"] += float(urban.sum()) * C.STEP / 1000
    good = (ma >= T_MIN) & rural
    # Runs of good samples; runs less than GAP apart (a short straight
    # between bends, never a town) are joined.
    idx = np.flatnonzero(np.diff(np.concatenate(([0], good.astype(np.int8), [0]))))
    runs = []
    for a, b in zip(idx[::2], idx[1::2]):
        if runs and (a - runs[-1][1]) * C.STEP < GAP and rural[runs[-1][1]:a].all():
            runs[-1] = (runs[-1][0], b)
        else:
            runs.append((a, b))
    for a, b in runs:
        length = (b - a) * C.STEP
        if length < L_MIN:
            continue
        out.append({"name": name, "cls": cls, "length": length, "twist": float(w[a:b].mean()),
                    "lonlat": lonlat[a:b]})


def simplify(lonlat: np.ndarray, tol_deg: float = 0.00012):
    from shapely.geometry import LineString
    g = LineString(lonlat).simplify(tol_deg, preserve_topology=False)
    return [[round(x, 5), round(y, 5)] for x, y in g.coords]


def build(pbf: Path, out: Path) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    roads, places_file = extract(pbf, out.parent / "work")
    ways = load_ways(roads)
    places = load_places(places_file)
    found, hist, nchains = [], [], 0
    for name, cls, coords in chains(ways):
        nchains += 1
        stretches(name, cls, coords, places, found, hist)
    print(f"chains: {nchains}; twisty stretches: {len(found)} in {time.time() - t0:.0f} s", flush=True)
    ma = np.concatenate(hist) if hist else np.zeros(1)
    share = {f">={t}": round(float((ma >= t).mean()), 4) for t in (0.2, 0.3, 0.45, 0.6, 0.8, 1.0)}
    cls_names = {v: k for k, v in CLASSES.items()}
    found.sort(key=lambda r: -r["length"] * r["twist"])
    roads_out = [{"n": r["name"], "c": cls_names.get(r["cls"], ""), "l": round(r["length"]),
                  "t": round(r["twist"], 3), "p": simplify(r["lonlat"])} for r in found]
    doc = {"kind": "byway-nav-twisty", "v": 1, "built": date.today().isoformat(),
           "params": {"window_m": WINDOW, "t_min": T_MIN, "l_min_m": L_MIN, "gap_m": GAP, "bins": C.BINS,
                      "sweep": [C.SWEEP_ARM, C.SWEEP_R, C.SWEEP_W], "step_m": C.STEP,
                      "arm_m": C.ARM, "places_m": PLACE_R},
           "attribution": "Twisty roads from OpenStreetMap data, © OpenStreetMap contributors (ODbL)",
           "roads": roads_out}
    raw = json.dumps(doc, separators=(",", ":")).encode()
    gz = gzip.compress(raw, 9)
    (out / "twisty-gb.json.gz").write_bytes(gz)
    preview(found, out / "preview.png")
    known = {}
    for ref in KNOWN:
        hits = [r for r in found if r["name"] == ref]
        known[ref] = {"stretches": len(hits), "km": round(sum(r["length"] for r in hits) / 1000, 1),
                      "best_twist": round(max((r["twist"] for r in hits), default=0), 2)}
    stats = {
        "built": doc["built"], "seconds": round(time.time() - t0), "ways": len(ways), "chains": nchains,
        "stretches": len(found), "km": round(sum(r["length"] for r in found) / 1000),
        "bytes_gz": len(gz), "bytes_raw": len(raw), "points": sum(len(r["p"]) for r in roads_out),
        "rural_road_share_by_1km_twist": share, "known_roads": known,
        "known_roads_chains": {k: {kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}
                               for k, v in DIAG.items()},
        "twist_hist": {f"{lo}-{lo + 0.1:.1f}": sum(1 for r in found if lo <= r["twist"] < lo + 0.1)
                       for lo in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)},
        "top": [{"n": r["name"] or "(unnamed)", "c": cls_names.get(r["cls"]), "km": round(r["length"] / 1000, 1),
                 "t": round(r["twist"], 2), "at": [round(float(r["lonlat"][0][1]), 4), round(float(r["lonlat"][0][0]), 4)]}
                for r in found[:40]],
        "by_class": dict(Counter(cls_names.get(r["cls"]) for r in found)),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=1))
    return stats


def preview(found, path: Path):
    from PIL import Image, ImageDraw
    W, H, west, north, dlon, dlat = 1313, 2220, -8.70, 60.95, 0.008, 0.005
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    for r in reversed(found):
        col = (230, 160, 0) if r["twist"] < 0.7 else (220, 60, 0) if r["twist"] < 1.0 else (150, 0, 120)
        pts = [((lo - west) / dlon, (north - la) / dlat) for lo, la in r["lonlat"][::5]]
        if len(pts) > 1:
            d.line(pts, fill=col, width=2)
    img.save(path, optimize=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--pbf", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(build(a.pbf, a.out), indent=1))
