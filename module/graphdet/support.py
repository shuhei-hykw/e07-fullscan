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
# Spacing of the samples along a polyline (px, unscaled coordinates).
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


def unsupported_fraction(polys: list, x: np.ndarray,
                         z_scale: float) -> np.ndarray:
  """Longest unsupported stretch of each polyline over its length.

  ``polys`` and the hits ``x`` (N, 3) share coordinates (x, y in px,
  z in slices); lengths are measured with z multiplied by
  ``z_scale``.
  """
  n_p = len(polys)
  if not n_p:
    return np.zeros(0)
  sp, sid = sample(polys)
  box = np.array([1.0, 1.0, SUPPORT_XY_PX / SUPPORT_Z_SLICES])
  d, _ = cKDTree(x * box).query(sp * box, p=np.inf,
                                distance_upper_bound=SUPPORT_XY_PX)
  has = np.isfinite(d)
  scale = np.array([1.0, 1.0, z_scale])
  start = np.r_[True, sid[1:] != sid[:-1]]
  step = np.r_[0.0, np.linalg.norm(np.diff(sp, axis=0) * scale, axis=1)]
  step[start] = 0.0
  # A run of unsupported samples restarts at every supported sample
  # and at every polyline start
  run = np.cumsum(has | start)
  gap_run = np.bincount(run, np.where(has, 0.0, step))
  gap = np.zeros(n_p)
  np.maximum.at(gap, sid, gap_run[run])
  length = np.array([np.linalg.norm(np.diff(p, axis=0) * scale,
                                    axis=1).sum() for p in polys])
  return gap / np.maximum(length, MIN_LENGTH_PX)


def filter_polylines(polys: list, x: np.ndarray, z_scale: float,
                     max_frac: float) -> tuple[list, np.ndarray]:
  """Polylines whose unsupported fraction is at most ``max_frac``,
  and the keep mask."""
  keep = unsupported_fraction(polys, x, z_scale) <= max_frac
  return [p for p, k in zip(polys, keep) if k], keep
