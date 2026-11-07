"""How twisty a road is, for the app's "Road fun" routing.

Same rules as lib/nav/curvature.dart (the app scores routes with them):

  * the line is resampled every STEP (10 m);
  * at each sample, the radius of the circle through the samples ARM
    (30 m) before and after it, clamped at the ends (so only the first and
    last sample read as straight);
  * each sample gets a weight from that radius: under 30 m 4 (hairpin),
    30–60 m 3, 60–100 m 2, 100–175 m 1;
  * wider bends are measured again over SWEEP_ARM (80 m each way, so
    mapping wobble can't fake them): under 400 m is a sweeping bend, 0.5;
    anything wider is straight, 0;
  * twistiness = the mean weight (0 = dead straight; a good B-road over
    the moors is around 0.5–1).

Coordinates are local metres (x east, y north); `to_metres` turns lon/lat
into them with a flat projection, which is plenty over a few km.
"""
from __future__ import annotations

import math

import numpy as np

STEP = 10.0
ARM = 30.0
BINS = ((30.0, 4.0), (60.0, 3.0), (100.0, 2.0), (175.0, 1.0))
SWEEP_ARM, SWEEP_R, SWEEP_W = 80.0, 400.0, 0.5


def to_metres(lonlat, lat0: float | None = None) -> np.ndarray:
    a = np.asarray(lonlat, dtype=float)
    lat0 = float(np.mean(a[:, 1])) if lat0 is None else lat0
    return np.column_stack((a[:, 0] * 111320.0 * math.cos(math.radians(lat0)), a[:, 1] * 110540.0))


def resample(xy: np.ndarray, step: float = STEP) -> np.ndarray:
    """Points every [step] metres along the line, ends included."""
    xy = np.asarray(xy, dtype=float)
    if len(xy) < 2:
        return xy
    seg = np.hypot(*np.diff(xy, axis=0).T)
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    total = cum[-1]
    if total <= 0:
        return xy[:1]
    n = max(1, int(total // step))
    s = np.linspace(0.0, total, n + 1)
    return np.column_stack((np.interp(s, cum, xy[:, 0]), np.interp(s, cum, xy[:, 1])))


def radii(samples: np.ndarray, step: float = STEP, arm: float = ARM) -> np.ndarray:
    """Circle radius at each sample through the samples [arm] before and
    after (indices clamped at the ends); inf where straight."""
    n = len(samples)
    if n < 3:
        return np.full(n, np.inf)
    k = max(1, int(round(arm / step)))
    i = np.arange(n)
    a, b, c = samples[np.clip(i - k, 0, n - 1)], samples, samples[np.clip(i + k, 0, n - 1)]
    ab, bc, ca = np.hypot(*(b - a).T), np.hypot(*(c - b).T), np.hypot(*(a - c).T)
    cross = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = ab * bc * ca / (2.0 * cross)
    r[~np.isfinite(r)] = np.inf
    return r


def weights(r: np.ndarray) -> np.ndarray:
    w = np.zeros(len(r))
    for limit, value in reversed(BINS):  # wide to tight, tighter overwrites
        w[r < limit] = value
    return w


def sample_weights(xy) -> np.ndarray:
    """Weight of each 10 m sample along a line (local metres)."""
    return weights_of(resample(xy))


def weights_of(samples: np.ndarray) -> np.ndarray:
    """Weights of resampled points: tight bends, then sweeping ones."""
    w = weights(radii(samples))
    sweep = (w == 0) & (radii(samples, arm=SWEEP_ARM) < SWEEP_R)
    w[sweep] = SWEEP_W
    return w


def twistiness(xy) -> float:
    w = sample_weights(xy)
    return float(w.mean()) if len(w) else 0.0
