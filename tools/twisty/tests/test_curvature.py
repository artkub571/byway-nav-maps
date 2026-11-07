import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import curvature as C  # noqa: E402


def arc(radius, length, step=1.0):
    n = int(length / step)
    return np.array([[radius * math.sin(i * step / radius), radius * (1 - math.cos(i * step / radius))]
                     for i in range(n + 1)])


def test_radius_bins():
    for r, w in ((20, 4), (45, 3), (80, 2), (140, 1), (250, 0.5), (600, 0)):
        ws = C.sample_weights(arc(r, 400))
        inner = ws[8:-8]  # the ends read as straight
        assert set(inner.tolist()) == {float(w)}, (r, set(inner.tolist()))


def test_straight_and_short():
    assert C.twistiness(np.array([[0, 0], [1000, 0]])) == 0.0
    assert C.twistiness(np.array([[0, 0]])) == 0.0


def test_shared_case_with_dart():
    # Also in test/curvature_test.dart: a 50 m-radius arc of 195 1-m steps
    # (194.997 m of chords): 20 samples, the 18 inner ones weigh 3.
    assert len(C.resample(arc(50, 195))) == 20
    assert abs(C.twistiness(arc(50, 195)) - 18 * 3 / 20) < 1e-9


def test_to_metres():
    xy = C.to_metres([[-2.0, 52.0], [-1.99, 52.01]], lat0=52.0)
    assert abs((xy[1, 0] - xy[0, 0]) - 685.4) < 1
    assert abs((xy[1, 1] - xy[0, 1]) - 1105.4) < 1
