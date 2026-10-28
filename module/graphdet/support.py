"""How evenly the hits support each stage-2 polyline.

Not part of the MATLAB original. With a dense hit cloud (one hit per
detected grain, e.g. the 3-D DoG point cloud) stage 2 also chains
hits that do not belong to one track, and such polylines tend to
bridge long stretches with no hit near them. The measure is the
longest stretch of a polyline with no hit in a small box around it,
as a fraction of the polyline's length; a hit count would also drop
the short, heavily ionising tracks the search is for.

A dropped polyline can still carry a short real track chained to a
long unsupported bridge, so its supported pieces (split at long
unsupported runs) can be kept instead of discarding it whole.
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
# Salvage of dropped polylines: split at unsupported runs longer than
# this, keep pieces at least SALVAGE_MIN_PX long (both z-scaled px).
SALVAGE_CUT_PX = 10.0
SALVAGE_MIN_PX = 10.0


def sample(polys: list, z_scale: float = 1.0,
           step: float = SAMPLE_STEP_PX) -> tuple[np.ndarray, np.ndarray]:
  """Points at every ``step`` of z-scaled arc length along each
  polyline, plus its end, with the polyline index. The positions do
  not depend on how many vertices a polyline is drawn with."""
  scale = np.array([1.0, 1.0, z_scale])
  pts, ids = [], []
  for i, p in enumerate(polys):
    cum = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(p, axis=0) * scale,
                                              axis=1))]
    at = np.r_[np.arange(0.0, cum[-1], step), cum[-1]]
    pts.append(np.column_stack([np.interp(at, cum, p[:, k])
                                for k in range(p.shape[1])]))
    ids.append(np.full(len(at), i))
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


def _support(polys: list, x: np.ndarray, z_scale: float, step: float):
  """Samples along the polylines and, per sample, whether a hit
  supports it and the scaled length of the unsupported run it is in
  (0 if supported)."""
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
  return sp, sid, step_len, start, np.where(has, 0.0, gap_run[run])


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
  _, sid, step_len, _, run_len = _support(polys, x, z_scale, step)
  gap = np.zeros(n_p)
  np.maximum.at(gap, sid, run_len)
  length = np.bincount(sid, step_len, n_p)
  return gap / np.maximum(length, MIN_LENGTH_PX)


def supported_pieces(polys: list, x: np.ndarray, z_scale: float,
                     cut: float = SALVAGE_CUT_PX,
                     min_len: float = SALVAGE_MIN_PX,
                     step: float = SAMPLE_STEP_PX,
                     with_parent: bool = False):
  """Polylines split at unsupported runs longer than ``cut``; pieces
  shorter than ``min_len`` are dropped. Pieces are the samples.

  With ``with_parent`` also returns, per piece, the index of the
  polyline it came from and whether its start / end is a cut (not an
  end of that polyline), shape (n, 2)."""
  if not len(polys):
    return ([], np.zeros(0, int), np.zeros((0, 2), bool)) \
      if with_parent else []
  sp, sid, step_len, start, run_len = _support(polys, x, z_scale, step)
  bad = run_len > cut
  keep = ~bad
  # A piece starts at each polyline start and after removed samples
  new = keep & (start | np.r_[True, bad[:-1]])
  pid = np.cumsum(new)[keep]
  pts, seg = sp[keep], np.where(new, 0.0, step_len)[keep]
  # A sample is a polyline end if the next / previous sample is not on
  # the same polyline
  last = np.r_[sid[1:] != sid[:-1], True][keep]
  first = start[keep]
  parent = sid[keep]
  bounds = np.flatnonzero(np.diff(pid)) + 1
  out, par, cut_end = [], [], []
  for idx in np.split(np.arange(len(pid)), bounds):
    if len(idx) >= 2 and seg[idx].sum() >= max(min_len, MIN_LENGTH_PX):
      out.append(pts[idx])
      par.append(parent[idx[0]])
      cut_end.append((not first[idx[0]], not last[idx[-1]]))
  if not with_parent:
    return out
  return out, np.array(par, int), np.array(cut_end, bool).reshape(-1, 2)


def filter_polylines(polys: list, x: np.ndarray, z_scale: float,
                     max_frac: float,
                     salvage: bool = False) -> tuple[list, np.ndarray]:
  """Polylines whose unsupported fraction is at most ``max_frac``,
  and the keep mask. With ``salvage`` the supported pieces of the
  dropped ones (supported_pieces) are appended after them."""
  keep = unsupported_fraction(polys, x, z_scale) <= max_frac
  kept = [p for p, k in zip(polys, keep) if k]
  if salvage:
    kept += supported_pieces([p for p, k in zip(polys, keep) if not k],
                             x, z_scale)
  return kept, keep
