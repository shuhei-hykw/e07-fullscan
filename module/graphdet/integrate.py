"""Port of integrate_smallregions.m: sub-region segments -> tracks.

Stage 1 of the detector runs independently on each 128x128x80 block,
so a track crossing a block boundary comes out as several unrelated
segments. This stage stitches them back together in three passes:

1. Greedily chain segments end to end, longest first, accepting a
   neighbour only if the pair still reads as one straight line
   (``isaline3``).
2. Re-fit each chain against the original hits, which both cleans up
   the seams and lets a chain that swallowed a second track's hits be
   detected as a duplicate and dropped.
3. Join whole polylines end to end on a much looser, angle-based
   criterion (``isaline3a``), then re-fit the ones that changed.

Pass 3 is where a track survives a real gap: pass 1 only ever joins
segments that are nearly touching, so a track interrupted by a missing
block stays broken until here.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .config import MATLAB_CONFIG, DetectorConfig
from .geom import is_a_line3, is_a_line3a, min_distance_to_polyline, norma
from .polyfit import pixellist_to_poly
# Slack (px) on the "is this hit inside the polyline's extent?" test.
# A polyline's end vertex IS the projection of its outermost hit, so
# that hit sits at arc length exactly 0 (or exactly lpoly) in exact
# arithmetic and lands on either side of the test at the 1e-13 level.
# MATLAB compares against a bare 0 and therefore keeps or drops those
# two hits per polyline according to the last bit of its own BLAS --
# which is not reproducible here, and not worth reproducing: dropping
# them shrinks the fit by ~1 px each pass and can starve a short
# polyline of hits entirely. Including them is what the comparison
# means in exact arithmetic, and it makes the result deterministic.
_ELL_SLACK_PX = 1e-9
# Drop a polyline once this fraction of its hits is also claimed by
# other polylines -- it is a duplicate of, or a detour through, them.
_MAX_SHARED_FRACTION = 0.8
# Pass-3 join limits, in degrees of kink at the junction. The looser
# two only apply when the candidate is the ONLY plausible
# continuation, and the loosest also requires the other polyline to be
# short: a stub has a poorly determined direction, so its angle is
# weak evidence either way. Angles, so they do not scale with spacing
# and stay out of DetectorConfig.
_JOIN_ANGLE_DEG = 5.0
_JOIN_ANGLE_SOLE_DEG = 20.0
_JOIN_ANGLE_SOLE_SHORT_DEG = 40.0


def _neighbour_box(cfg: DetectorConfig) -> np.ndarray:
  return np.array([cfg.neighbour_xy, cfg.neighbour_xy, cfg.neighbour_z])


class _EndpointIndex:
  """Box queries over segment endpoints, without scanning all of them.

  MATLAB tests every endpoint of every segment against the search box
  on every extension step, which is O(M) per step and O(M^2) per view
  -- fine for the simulation's 1,239 segments, hours for the 44,360 a
  real E07 tile produces. Dividing by the box half-widths turns the
  test into a Chebyshev ball of radius 1, which a k-d tree answers
  directly.

  Segments are never moved, only consumed (set to NaN), so the tree is
  built once. A consumed segment fails the exact re-check below --
  every NaN comparison is false -- exactly as in MATLAB.
  """

  def __init__(self, lseg: np.ndarray, box: np.ndarray):
    self.lseg, self.box = lseg, box
    self.m = lseg.shape[2]
    ends = np.concatenate([lseg[0].T, lseg[1].T], axis=0) / box
    self.tree = cKDTree(np.nan_to_num(ends, nan=np.inf))

  def near(self, point: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Segment and endpoint indices, in MATLAB's find() order.

    find() on the (2, M) mask walks column-major, i.e. by segment and
    then by endpoint; ties in the later min() are broken by this
    order, so it has to be reproduced exactly.
    """
    idx = np.asarray(
      self.tree.query_ball_point(point / self.box, 1.0, p=np.inf),
      dtype=np.int64)
    if idx.size == 0:
      return idx, idx
    ends, segs = idx // self.m, idx % self.m
    with np.errstate(invalid="ignore"):
      keep = np.all(
        np.abs(self.lseg[ends, :, segs] - point[None, :]) < self.box,
        axis=1)
    ends, segs = ends[keep], segs[keep]
    order = np.lexsort((ends, segs))
    return segs[order], ends[order]


def _chain_segments(lseg: np.ndarray,
                     cfg: DetectorConfig = MATLAB_CONFIG) -> list:
  """Pass 1: chain segments into polylines, longest seed first."""
  box = _neighbour_box(cfg)
  lengths = norma(np.diff(lseg, axis=0)[0], 0)
  order = np.argsort(-lengths, kind="stable")
  lengths, lseg = lengths[order], lseg[:, :, order].copy()

  index = _EndpointIndex(lseg, box)
  polylines = []
  for i in range(lseg.shape[2]):
    if np.isnan(lseg[0, 0, i]) or lengths[i] == 0:
      continue
    poly = lseg[:, :, i].copy()
    lseg[:, :, i] = np.nan
    for forward in (False, True):
      while True:
        # The stub handed to isaline3 is the whole chain's chord, not
        # its last segment: a chain that has already bent should not
        # keep growing along its latest piece.
        stub = poly[[-1, 0]] if forward else poly[[0, -1]]
        segs, ends = index.near(stub[0])
        if segs.size == 0:
          break
        d = np.array([
          is_a_line3(stub, lseg[[e, 1 - e], :, s], cfg)
          for s, e in zip(segs, ends)])
        k = int(np.argmin(d))
        if np.isinf(d[k]):
          break
        other = lseg[[ends[k], 1 - ends[k]], :, segs[k]]
        poly = (np.vstack([poly, other]) if forward
                else np.vstack([other[::-1], poly]))
        lseg[:, :, segs[k]] = np.nan
      # end of one direction
    polylines.append(poly)
  return polylines


def _resample(
  polylines: list[np.ndarray], x: np.ndarray,
  cfg: DetectorConfig = MATLAB_CONFIG, dim: int = 3,
) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
  """Port of resamplingpoly: re-fit each polyline to the hits it owns.

  Returns the surviving polylines, their lengths, and the keep mask
  over the input (the caller needs the mask to know which entries
  vanished).
  """
  th = cfg.resample_th
  n, m = x.shape[0], len(polylines)
  lengths = np.zeros(m)
  owned = np.zeros((n, m), dtype=bool)
  refit = []
  for i, poly in enumerate(polylines):
    ell, err, _, lpoly = min_distance_to_polyline(poly, x)
    sel = ((ell >= -_ELL_SLACK_PX) & (ell <= lpoly + _ELL_SLACK_PX)
           & (err < th))
    owned[sel, i] = True
    idx = np.flatnonzero(sel)
    if idx.size == 0:
      # Nothing to re-fit; leave it at zero length and the next pass
      # will skip it.
      refit.append(poly)
      continue
    idx = idx[np.argsort(ell[idx], kind="stable")]
    fit = pixellist_to_poly(x[idx], dim, th)
    refit.append(fit[0])
    lengths[i] = fit[5]

  # float32 counts stay exact well past any plausible hit count and
  # keep this a single BLAS call instead of a 100s-of-MB int matmul.
  e = owned.astype(np.float32)
  shared = e.T @ e
  own_counts = np.diag(shared).copy()
  np.fill_diagonal(shared, 0.0)
  with np.errstate(invalid="ignore", divide="ignore"):
    ratio = shared.sum(axis=1) / own_counts
  # NaN (a polyline that owns nothing) compares false and is kept,
  # matching MATLAB.
  keep = ~(ratio > _MAX_SHARED_FRACTION)
  return ([p for p, k in zip(refit, keep) if k], lengths[keep], keep)


def _join_polylines(
  polylines: list[np.ndarray], lengths: np.ndarray,
  cfg: DetectorConfig = MATLAB_CONFIG,
) -> tuple[list[np.ndarray], list[bool]]:
  """Pass 3: join whole polylines end to end on the angle criterion."""
  if not polylines:
    return [], []
  lseg = np.stack([p[[0, -1]] for p in polylines], axis=2).astype(float)
  index = _EndpointIndex(lseg, _neighbour_box(cfg))
  joined: list[np.ndarray] = []
  changed: list[bool] = []
  for i in range(len(polylines)):
    if np.isnan(lseg[0, 0, i]) or lengths[i] == 0:
      continue
    cur = polylines[i].copy()
    lseg[:, :, i] = np.nan
    joined.append(cur)
    changed.append(False)
    for forward in (False, True):
      while True:
        # Here the stub IS the last two points: after pass 2 a
        # polyline may genuinely bend, so its chord says nothing about
        # which way it leaves either end.
        stub = joined[-1][[-1, -2]] if forward else joined[-1][[0, 1]]
        segs, ends = index.near(stub[0])
        if segs.size == 0:
          break
        d = np.array([
          is_a_line3a(
            stub, polylines[s][[0, 1] if e == 0 else [-1, -2]], cfg)
          for s, e in zip(segs, ends)])
        k = int(np.argmin(d))
        sole = int(np.isfinite(d).sum()) == 1
        if not (d[k] < _JOIN_ANGLE_DEG
                or (sole and d[k] < _JOIN_ANGLE_SOLE_DEG)
                or (sole and lengths[segs[k]] < cfg.join_short_poly
                    and d[k] < _JOIN_ANGLE_SOLE_SHORT_DEG)):
          break
        other = polylines[segs[k]]
        head_join = ends[k] == 0
        if forward:
          joined[-1] = np.vstack(
            [joined[-1], other if head_join else other[::-1]])
        else:
          joined[-1] = np.vstack(
            [other[::-1] if head_join else other, joined[-1]])
        lseg[:, :, segs[k]] = np.nan
        changed[-1] = True
  return joined, changed


def integrate_smallregions(
  x: np.ndarray, lseg: np.ndarray,
  cfg: DetectorConfig = MATLAB_CONFIG,
) -> list[np.ndarray]:
  """Port of integrate_smallregions.m.

  ``x`` is the (N, 3) hit cloud of one view and ``lseg`` the (2, 3, M)
  segments from detect_lseg_view. Returns one (K+1, 3) array of
  polyline vertices per reconstructed track.
  """
  x = np.asarray(x, dtype=float)
  polylines = _chain_segments(np.asarray(lseg, dtype=float), cfg)
  polylines, lengths, _ = _resample(polylines, x, cfg)
  order = np.argsort(-lengths, kind="stable")
  polylines = [polylines[i] for i in order]
  lengths = lengths[order]

  polylines, changed = _join_polylines(polylines, lengths, cfg)
  idx = [i for i, c in enumerate(changed) if c]
  if idx:
    # MATLAB writes the re-fit polylines straight back over the ones
    # that changed, which errors out if _resample dropped any. It
    # never did on the reference run; here a dropped polyline is
    # simply removed, which is what the assignment was meant to do.
    refit, _, keep = _resample([polylines[i] for i in idx], x, cfg)
    for i, k in zip(idx, keep):
      polylines[i] = None if not k else refit.pop(0)
    polylines = [p for p in polylines if p is not None]
  return polylines
