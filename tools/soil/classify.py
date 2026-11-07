"""Drainage classes for the app's mud forecast (pure functions, no GIS).

A lane on chalk or sandstone dries within a day or two; one on clay, till or
peat stays muddy for days after the same rain. The soil-moisture model the
app uses (ECMWF, ~9 km squares) can't see that, so each ~500 m cell of
Great Britain gets a class from BGS Geology 625k (superficial deposits over
bedrock) adjusted by SoilGrids topsoil clay:

    0 unknown (sea / no data)   1 drains fast   2 average   3 drains slowly

Mud-cautious on mixed ground: a description that starts with a clay-type
rock is "slow"; a fast rock mixed with clay-type rocks is only "average".
"""
from __future__ import annotations

import re

UNKNOWN, FAST, MEDIUM, SLOW = 0, 1, 2, 3
NAMES = ["unknown", "fast", "medium", "slow"]

_FAST = ("CHALK", "LIMESTONE", "DOLOSTONE", "DOLOMITE", "SANDSTONE", "GRITSTONE", "GRIT",
         "CONGLOMERATE", "BRECCIA", "GRAVEL", "SAND")
_SLOW = ("MUDSTONE", "CLAYSTONE", "CLAY", "SHALE", "SILTSTONE", "SLATE", "MARL", "SILT",
         "PEAT", "TILL", "DIAMICTON")
_WORDS = re.compile(r"\b(" + "|".join(sorted(_FAST + _SLOW, key=len, reverse=True)) + r")\b")
# Superficial deposits that hold water whatever their sand content.
_WET_DEPOSITS = re.compile(r"\b(PEAT|TILL|DIAMICTON|BOULDER CLAY|ALLUVIUM|LACUSTRINE|TIDAL|MARINE|ESTUARINE)\b")
_HEAD = re.compile(r"\bHEAD\b")


def _rock(text: str) -> int | None:
    """Class from the rock words in a description, or None without any."""
    words = [m.group(1) for m in _WORDS.finditer((text or "").upper())]
    if not words:
        return None
    if words[0] in _SLOW:
        return SLOW
    return MEDIUM if any(w in _SLOW for w in words) else FAST


def bedrock_class(rock: str, name: str = "") -> int:
    """Bedrock: rock description first (e.g. "CHALK", "MUDSTONE, SILTSTONE
    AND SANDSTONE"), then the unit name. Igneous and metamorphic rocks
    without a listed word count as average."""
    c = _rock(rock)
    if c is None:
        c = _rock(name)
    return MEDIUM if c is None else c


def superficial_class(name: str, rock: str = "") -> int:
    """Superficial deposits (drawn over the bedrock). Peat, till, alluvium
    and other water-laid clays are slow; head is average; sand and gravel
    (river terraces, glaciofluvial, blown sand) is fast. UNKNOWN keeps the
    bedrock class."""
    text = f"{name or ''} | {rock or ''}".upper()
    if _WET_DEPOSITS.search(text):
        return SLOW
    if _HEAD.search(text):
        return MEDIUM
    c = _rock(rock)
    if c is None:
        c = _rock(name)
    return UNKNOWN if c is None else c


def with_clay(cls: int, clay_pct: float | None) -> int:
    """SoilGrids topsoil clay (0–5 cm, %) moves a cell towards "slow":
    sticky clay soil over chalk or sandstone stays muddy (e.g. clay-with-
    flints on the downs). It never makes a cell faster."""
    if clay_pct is None or clay_pct < 0:
        return cls
    if cls == UNKNOWN:
        return UNKNOWN  # sea or outside the geology map
    if cls == FAST and clay_pct >= 30:
        return MEDIUM
    if cls == MEDIUM and clay_pct >= 35:
        return SLOW
    return cls


def pack(cells) -> bytes:
    """2 bits per cell, row-major; cell i is in byte i >> 2 at bits
    (i & 3) * 2. Same as DrainageGrid in lib/services/soil.dart."""
    n = len(cells)
    out = bytearray((n + 3) // 4)
    for i, c in enumerate(cells):
        if c:
            out[i >> 2] |= (int(c) & 3) << ((i & 3) * 2)
    return bytes(out)


def unpack(data: bytes, n: int) -> list[int]:
    return [(data[i >> 2] >> ((i & 3) * 2)) & 3 for i in range(n)]
