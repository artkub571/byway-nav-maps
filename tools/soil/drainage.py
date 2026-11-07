"""Builds the soil drainage map for the app's mud forecast.

    python tools/soil/drainage.py build --out <dir>

Writes <dir>/drainage-gb.bin.gz (a ~500 m grid of Great Britain and
Northern Ireland, 2 bits per cell, see classify.py and
lib/services/soil.dart), preview.png and stats.json. Runs in GitHub Actions
(Actions → Soil drainage map): BGS and ISRIC can't be reached from the dev
sandbox.

Sources:
  * BGS Geology 625k (DiGMapGB-625), bedrock and superficial deposits:
    Open Government Licence. "Contains British Geological Survey materials
    © UKRI".
  * SoilGrids 2.0 topsoil clay (0–5 cm, 250 m): ISRIC, CC BY 4.0.
"""
from __future__ import annotations

import argparse
import gzip
import html
import io
import json
import re
import sys
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify as C  # noqa: E402

WEST, NORTH, DLON, DLAT = -8.70, 60.95, 0.008, 0.005
COLS, ROWS = 1313, 2220  # to 1.804°E, 49.85°N
BGS_PAGE = "https://www.bgs.ac.uk/datasets/bgs-geology-625k-digmapgb/"
SOILGRIDS_CLAY = "/vsicurl/https://files.isric.org/soilgrids/latest/data/clay/clay_0-5cm_mean.vrt"
UA = {"User-Agent": "byway-nav soil-drainage builder (personal app)"}
SITES = [
    ("Salisbury Plain (chalk)", 51.250, -1.950),
    ("Ridgeway, Uffington (chalk)", 51.565, -1.580),
    ("Vale of Aylesbury (clay)", 51.850, -0.950),
    ("Sussex Weald (clay)", 51.050, -0.350),
    ("Haccombe, Devon", 50.520, -3.560),
    ("Dartmoor (granite, peat)", 50.580, -3.950),
    ("Peak District, Long Causeway", 53.360, -1.630),
    ("Yorkshire Dales (limestone)", 54.200, -2.100),
    ("Breckland (sand)", 52.450, 0.700),
    ("Fens (peat/clay)", 52.450, 0.050),
]


def fetch(url: str) -> tuple[bytes, str]:
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except Exception as e:  # noqa: BLE001
            print(f"  fetch failed ({e}); retrying", flush=True)
            time.sleep(5 * (k + 1))
    raise RuntimeError(f"could not fetch {url}")


def bgs_archive() -> bytes:
    """Finds the GeoPackage (or shapefile) download on the BGS dataset page,
    following one intermediate download page if needed."""
    page, _ = fetch(BGS_PAGE)
    text = page.decode("utf-8", "replace")
    links = [(html.unescape(h), re.sub(r"<[^>]+>", " ", t)) for h, t in
             re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S)]
    cands = [h for h, t in links if re.search(r"geopackage|gpkg", h + " " + t, re.I)]
    cands += [h for h, t in links if re.search(r"shape", h + " " + t, re.I) and h not in cands]
    print("BGS download candidates:", cands[:6], flush=True)
    # Prefer the 625k packages (the shapefile page names the dataset).
    cands.sort(key=lambda h: (0 if "625k" in h and "polygon" in h else 1 if "625k" in h else 2))
    for url in cands:
        body, ctype = fetch(url)
        if body[:2] == b"PK":
            print(f"  {url}: zip, {len(body) / 1e6:.1f} MB", flush=True)
            return body
        page = html.unescape(body.decode("utf-8", "replace"))
        # WordPress Download Manager pages: the file is behind ?wpdmdl=<id>.
        inner = re.findall(r'(https?://[^"\'\s<>]*wpdmdl=\d+[^"\'\s<>]*)', page)
        inner += re.findall(r'data-downloadurl="([^"]+)"', page)
        inner += re.findall(r'href="([^"]+\.zip)"', page)
        ids = re.findall(r'(?:wpdmdl=|data-package-id="|data-id="|wpdm-download-link[^>]*?data-id=")(\d+)', page)
        inner += [f"{url.rstrip('/')}/?wpdmdl={i}" for i in dict.fromkeys(ids)]
        inner = list(dict.fromkeys(inner))
        print(f"  {url}: {ctype}, inner links {inner[:6]}", flush=True)
        if not inner:
            for m in list(re.finditer(r"wpdm|download", page, re.I))[:5]:
                print("    …", re.sub(r"\s+", " ", page[max(0, m.start() - 150): m.end() + 250]), flush=True)
        for u in inner:
            b2, _ = fetch(u)
            if b2[:2] == b"PK":
                print(f"  {u}: zip, {len(b2) / 1e6:.1f} MB", flush=True)
                return b2
    raise RuntimeError("no BGS 625k download found")


def load_layers(zbytes: bytes, work: Path):
    import geopandas as gpd
    import pyogrio

    z = zipfile.ZipFile(io.BytesIO(zbytes))
    z.extractall(work)
    files = sorted(p for p in work.rglob("*") if p.suffix.lower() in (".gpkg", ".shp"))
    print("BGS files:", [str(p.relative_to(work)) for p in files], flush=True)
    layers = []
    for f in files:
        for name, gtype in pyogrio.list_layers(f):
            layers.append((f, name, gtype))
    print("layers:", [(n, g) for _, n, g in layers], flush=True)

    def pick(word):
        for f, n, g in layers:
            if word in f"{f.name} {n}".lower() and "polygon" in (g or "").lower():
                return gpd.read_file(f, layer=n)
        for f, n, g in layers:
            if word in f"{f.name} {n}".lower() and "line" not in f"{f.name} {n}".lower():
                return gpd.read_file(f, layer=n)
        return None

    bed, sup = pick("bedrock"), pick("superficial")
    for label, g in (("bedrock", bed), ("superficial", sup)):
        if g is not None:
            print(f"{label}: {len(g)} polygons, crs {g.crs}, columns {list(g.columns)}", flush=True)
            print(g.drop(columns="geometry").head(3).to_string()[:1500], flush=True)
    if bed is None:
        raise RuntimeError("no bedrock layer")
    return bed, sup


def _field(g, *names):
    for n in names:
        for c in g.columns:
            if c.upper() == n:
                return c
    return None


def _s(v) -> str:
    """Attribute text; empty for missing values (NaN)."""
    return "" if v is None or v != v else str(v)


def classify_layers(bed, sup):
    rock = _field(bed, "RCS_D", "LEX_RCS_D", "ROCK_D")
    name = _field(bed, "LEX_D", "NAME")
    print("bedrock fields:", rock, name, flush=True)
    bed = bed.to_crs(4326)
    bed["cls"] = [C.bedrock_class(_s(r), _s(n)) for r, n in
                  zip(bed[rock] if rock else [""] * len(bed), bed[name] if name else [""] * len(bed))]
    fields = {"bedrock": [rock, name]}
    if sup is not None:
        # Superficial polygons keep their rock words in ROCK_D (RCS_D is often empty).
        rock = _field(sup, "ROCK_D", "RCS_D", "LEX_RCS_D")
        name = _field(sup, "LEX_D", "NAME")
        print("superficial fields:", rock, name, flush=True)
        sup = sup.to_crs(4326)
        sup["cls"] = [C.superficial_class(_s(n), _s(r)) for r, n in
                      zip(sup[rock] if rock else [""] * len(sup), sup[name] if name else [""] * len(sup))]
        fields["superficial"] = [rock, name]
    return bed, sup, fields


def rasterize(bed, sup):
    import numpy as np
    from rasterio.features import rasterize as rz
    from rasterio.transform import from_origin

    t = from_origin(WEST, NORTH, DLON, DLAT)

    def burn(g):
        shapes = ((geom, int(c)) for geom, c in zip(g.geometry, g["cls"]) if geom is not None and c)
        return rz(shapes, out_shape=(ROWS, COLS), transform=t, fill=0, dtype="uint8")

    grid = burn(bed)
    if sup is not None:
        s = burn(sup)
        grid = np.where(s > 0, s, grid).astype("uint8")
    return grid, t


def soilgrids_clay(t):
    """Topsoil clay % on the same grid, or None if SoilGrids can't be read."""
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    t0 = time.time()
    try:
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES",
                          GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", VSI_CACHE="TRUE",
                          GDAL_CACHEMAX=1024, GDAL_HTTP_MAX_RETRY=5, GDAL_HTTP_RETRY_DELAY=3):
            with rasterio.open(SOILGRIDS_CLAY) as src:
                print(f"SoilGrids: {src.width}x{src.height}, {src.crs}, nodata {src.nodata}", flush=True)
                with WarpedVRT(src, crs="EPSG:4326", transform=t, width=COLS, height=ROWS,
                               resampling=Resampling.average, src_nodata=src.nodata, nodata=-32768) as v:
                    a = v.read(1).astype("float32")
        a[a < 0] = np.nan
        print(f"SoilGrids read in {time.time() - t0:.0f} s; cells with data {np.isfinite(a).mean():.1%}", flush=True)
        return a / 10.0  # g/kg -> %
    except Exception as e:  # noqa: BLE001
        print(f"SoilGrids not used: {e}", flush=True)
        return None


def site_report(bed, sup, grid, clay, fields):
    import geopandas as gpd
    from shapely.geometry import Point

    out = []
    pts = gpd.GeoDataFrame({"site": [s[0] for s in SITES]},
                           geometry=[Point(lon, lat) for _, lat, lon in SITES], crs=4326)

    def desc(g, row):
        cols = [c for c in g.columns if c.upper() in ("LEX_D", "ROCK_D", "RCS_D")]
        return "; ".join(dict.fromkeys(_s(row[c]) for c in cols if _s(row[c])))

    for (name, lat, lon), p in zip(SITES, pts.geometry):
        r, c = int((NORTH - lat) / DLAT), int((lon - WEST) / DLON)
        b = bed[bed.contains(p)]
        s = sup[sup.contains(p)] if sup is not None else []
        out.append({
            "site": name,
            "class": C.NAMES[int(grid[r, c])],
            "bedrock": desc(bed, b.iloc[0]) if len(b) else "",
            "superficial": desc(sup, s.iloc[0]) if len(s) else "",
            "clay_pct": None if clay is None or clay[r, c] != clay[r, c] else round(float(clay[r, c]), 1),
        })
    return out


def build(out: Path) -> dict:
    import numpy as np
    from PIL import Image

    out.mkdir(parents=True, exist_ok=True)
    work = out.parent / "bgs"
    work.mkdir(parents=True, exist_ok=True)
    bed, sup = load_layers(bgs_archive(), work)
    bed, sup, fields = classify_layers(bed, sup)
    for label, g in (("bedrock", bed), ("superficial", sup)):
        if g is not None:
            print(label, "classes:", {C.NAMES[k]: int(v) for k, v in g["cls"].value_counts().items()}, flush=True)
    geo, t = rasterize(bed, sup)
    clay = soilgrids_clay(t)
    grid = geo.copy()
    if clay is not None:
        # classify.with_clay on every cell (no SoilGrids value -> -1 -> unchanged).
        f = np.vectorize(lambda cl, cp: C.with_clay(int(cl), float(cp)), otypes=[np.uint8])
        grid = f(geo, np.nan_to_num(clay, nan=-1.0))
    land = grid > 0
    shares = {C.NAMES[k]: round(float((grid == k).sum() / land.sum()), 3) for k in (1, 2, 3)}
    changed = int((grid != geo).sum())
    header = {
        "kind": "byway-nav-drainage", "v": 1, "built": date.today().isoformat(),
        "west": WEST, "north": NORTH, "dlon": DLON, "dlat": DLAT, "cols": COLS, "rows": ROWS,
        "classes": C.NAMES,
        "attribution": "Soil drainage from BGS Geology 625k (contains British Geological Survey materials © UKRI, "
                       "Open Government Licence)" + (" and SoilGrids topsoil clay (ISRIC, CC BY 4.0)" if clay is not None else ""),
    }
    raw = json.dumps(header, separators=(",", ":")).encode() + b"\n" + C.pack(grid.ravel().tolist())
    gz = gzip.compress(raw, 9)
    (out / "drainage-gb.bin.gz").write_bytes(gz)
    pal = [255, 255, 255, 236, 200, 90, 190, 160, 110, 110, 70, 40] + [0] * (256 * 3 - 12)
    img = Image.fromarray(grid, mode="P")
    img.putpalette(pal)
    img.save(out / "preview.png", optimize=True)
    stats = {
        "built": header["built"], "bytes_gz": len(gz), "bytes_raw": len(raw), "land_cells": int(land.sum()),
        "shares": shares, "cells_slowed_by_clay": changed, "soilgrids": clay is not None,
        "fields": fields, "sites": site_report(bed, sup, grid, clay, fields),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=1))
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(build(a.out), indent=1))
