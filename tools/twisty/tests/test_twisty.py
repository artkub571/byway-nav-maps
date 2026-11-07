import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import twisty as T  # noqa: E402


def way(key, cls, pts):
    return (key, cls, np.asarray(pts, dtype=float))


def test_chains_join_through_and_by_name():
    a, b, c, d, e = [-2.0, 52.0], [-2.0, 52.01], [-2.0, 52.02], [-1.99, 52.02], [-2.01, 52.02]
    ways = [
        way("B1", 3, [b, a]),          # reversed piece
        way("B1", 3, [b, c]),
        way("B1", 3, [c, [-2.0, 52.03]]),  # continues B1 through the junction at c
        way("", 1, [c, d]),            # side roads at c
        way("", 1, [c, e]),
    ]
    got = sorted((name, len(coords)) for name, _, coords in T.chains(ways))
    assert got == [("", 2), ("", 2), ("B1", 4)]
    b1 = next(coords for name, _, coords in T.chains(ways) if name == "B1")
    assert {tuple(b1[0]), tuple(b1[-1])} == {tuple(a), (-2.0, 52.03)}


def test_circular_road_ends():
    sq = [[0, 0], [0, 0.01], [0.01, 0.01], [0.01, 0]]
    ways = [way("", 1, [sq[0], sq[1]]), way("", 1, [sq[1], sq[2]]), way("", 1, [sq[2], sq[3]]),
            way("", 1, [sq[3], sq[0]])]
    assert sum(1 for _ in T.chains(ways)) == 1


def wiggle(km, amp_m, wave_m, lat=54.0):
    """A road heading north with sideways bends."""
    n = int(km * 1000 / 5)
    k = 111320.0 * math.cos(math.radians(lat))
    return np.array([[-2.0 + amp_m * math.sin(2 * math.pi * i * 5 / wave_m) / k, lat + i * 5 / 110540.0]
                     for i in range(n + 1)])


def test_twisty_stretch_found_and_town_cut():
    out, hist = [], []
    road = wiggle(6, 40, 250)  # tight-ish bends all the way
    T.stretches("B9", 3, road, {}, out, hist)
    assert len(out) == 1 and out[0]["length"] > 5000 and out[0]["twist"] > 1
    straight = np.array([[-2.0, 54.0], [-2.0, 54.06]])
    out2 = []
    T.stretches("A1", 4, straight, {}, out2, [])
    assert out2 == []
    # A village in the middle splits the road; both halves still over 2 km.
    mid = road[len(road) // 2]
    places = {(int(math.floor(mid[0] * 10)), int(math.floor(mid[1] * 10))): [(mid[0], mid[1], 500.0)]}
    out3 = []
    T.stretches("B9", 3, road, places, out3, [])
    assert len(out3) == 2
