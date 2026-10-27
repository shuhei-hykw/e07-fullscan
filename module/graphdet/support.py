"""How evenly the hits support each stage-2 polyline.

Not part of the MATLAB original. With a dense hit cloud (one hit per
detected grain, e.g. the 3-D DoG point cloud) stage 2 also chains
hits that do not belong to one track, and such polylines tend to
bridge long stretches with no hit near them. The measure is the
longest stretch of a polyline with no hit in a small box around it,
as a fraction of the polyline's length; a hit count would also drop
the short, heavily ionising tracks the search is for.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

# Box around a polyline sample in which a hit counts as support:
# reach in x/y (px) and in z (slices), both strict (closer than).
SUPPORT_XY_PX = 2.0
SUPPORT_Z_SLICES = 1.5
# Spacing of the samples along a polyline (z-scaled px).
SAMPLE_STEP_PX = 1.0
# Length floor (z-scaled px) so a zero-length polyline gives a finite
# fraction.
MIN_LENGTH_PX = 1.0


def sample(polys: list) -> tuple[np.ndarray, np.ndarray]:
  """Points every SAMPLE_STEP_PX along each polyline, with its index."""
  pts, ids = [], []
  for i, p in enumerate(polys):
    for a, b in zip(p[:-1], p[1:]):
      n = max(int(np.ceil(np.linalg.norm(b - a) / SAMPLE_STEP_PX)), 1)
      t = np.linspace(0.0, 1.0, n + 1)[:, None]
      pts.append(a + t * (b - a))
      ids.append(np.full(n + 1, i))
  if not pts:
    return np.zeros((0, 3)), np.zeros(0, int)
  return np.vstack(pts), np.concatenate(ids)


def _sample_scaled(polys: list, scale: np.ndarray, step: float):
  """Points every ``step`` (in z-scaled px) along each polyline, in the
  polylines' own coordinates, with the polyline index and the scaled
  distance from the previous point (0 at each polyline's start)."""
  pts, ids, gaps = [], [], []
  for i, p in enumerate(polys):
    for k, (a, b) in enumerate(zip(p[:-1], p[1:])):
      seg = np.linalg.norm((b - a) * scale)
      n = max(int(np.ceil(seg / step)), 1)
      t = np.linspace(0.0, 1.0, n + 1)[:, None]
      if k:
        t = t[1:]  # the shared vertex is already sampled
      pts.append(a + t * (b - a))
      ids.append(np.full(len(t), i))
      g = np.full(len(t), seg / n)
      if not k:
        g[0] = 0.0
      gaps.append(g)
  if not pts:
    return np.zeros((0, 3)), np.zeros(0, int), np.zeros(0)
  return np.vstack(pts), np.concatenate(ids), np.concatenate(gaps)


def unsupported_fraction(polys: list, x: np.ndarray, z_scale: float,
                         step: float = SAMPLE_STEP_PX) -> np.ndarray:
  """Longest unsupported stretch of each polyline over its length.

  ``polys`` and the hits ``x`` (N, 3) share coordinates (x, y in px,
  z in slices). Lengths, and the sampling, are in px with z
  multiplied by ``z_scale``, so a steep polyline is sampled as finely
  as a flat one.
  """
  n_p = len(polys)
  if not n_p:
    return np.zeros(0)
  scale = np.array([1.0, 1.0, z_scale])
  sp, sid, step_len = _sample_scaled(polys, scale, step)
  box = np.array([1.0, 1.0, SUPPORT_XY_PX / SUPPORT_Z_SLICES])
  d, _ = cKDTree(x * box).query(sp * box, p=np.inf,
                                distance_upper_bound=SUPPORT_XY_PX)
  has = np.isfinite(d)
  start = np.r_[True, sid[1:] != sid[:-1]]
  # A run of unsupported samples restarts at every supported sample
  # and at every polyline start
  run = np.cumsum(has | start)
  gap_run = np.bincount(run, np.where(has, 0.0, step_len))
  gap = np.zeros(n_p)
  np.maximum.at(gap, sid, gap_run[run])
  length = np.bincount(sid, step_len, n_p)
  return gap / np.maximum(length, MIN_LENGTH_PX)


def filter_polylines(polys: list, x: np.ndarray, z_scale: float,
                     max_frac: float) -> tuple[list, np.ndarray]:
  """Polylines whose unsupported fraction is at most ``max_frac``,
  and the keep mask."""
  keep = unsupported_fraction(polys, x, z_scale) <= max_frac
  return [p for p, k in zip(polys, keep) if k], keep
