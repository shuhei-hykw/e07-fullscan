"""Geometry helpers ported from the MATLAB graph track detector.

One-to-one ports of ``norma.m``, ``distfun1.m``, ``isaline5.m``,
``isaline6.m``, ``mindistance_tolineseg.m`` and the ``L2lseg`` /
``lseg2L`` subfunctions of ``detectlseg_smallregion.m`` (see
``e07/matlab``).

Behaviour is deliberately kept identical to the MATLAB originals down
to tie-breaking, so that a port can be checked against the reference
run stored in ``e07/matlab/work1.mat``. Where MATLAB semantics are
surprising -- a stale buffer, a first-of-equals ``max`` -- the Python
side reproduces them and says so in a comment rather than quietly
improving on them. Retuning belongs in a later step, once the port is
known to agree.
"""
from __future__ import annotations

import numpy as np

# distfun1.m scales the slice axis so that one z step is comparable to
# an x/y pixel: the simulation the detector was tuned on has 3 um
# slices at 0.29 um/px. E07 full-scan data is 1.5 um/slice, so this
# default is wrong for real data by a factor of two -- it is kept only
# to reproduce the reference run, and callers should pass their own.
MATLAB_Z_SCALE = 3.0 / 0.29

# isaline5.m: two single-point components join if they are this close.
_SINGLE_POINT_MAX_DIST = 20.0

# isaline5.m: a gap wider than this many times the mean point spacing
# means the two components are separate tracks.
_GAP_FACTOR = 15.0


def norma(x: np.ndarray, axis: int) -> np.ndarray:
  """Port of norma.m: Euclidean norm along one axis."""
  return np.sqrt(np.sum(x ** 2, axis=axis))


def scale_z(x: np.ndarray, z_scale: float) -> np.ndarray:
  """Port of distfun1.m: isotropic coordinates for distance work.

  distfun1 is passed to ``pdist`` as a custom metric, which hides the
  fact that it is a plain Euclidean distance on scaled coordinates --
  so in Python the scaling can be applied once and the distance
  vectorised. (The non-linear ``distfun.m``, which collapses adjacent
  slices to distance zero, is only reachable from pixellist2poly's
  flag=2/3 branches and the production path never takes them.)
  """
  return x * np.array([1.0, 1.0, z_scale])


def is_a_line(x: np.ndarray, th: float) -> bool:
  """Port of isaline6.m: do these points lie on one straight line?

  Fits the principal axis and asks for the largest perpendicular
  residual. Two points or fewer are always collinear.
  """
  if x.shape[0] <= 2:
    return True
  mu = x.mean(axis=0)
  _, _, vt = np.linalg.svd(x - mu, full_matrices=True)
  y = (x - mu) @ vt.T
  return not norma(y[:, 1:], 1).max() > th


def is_same_track(
  x1: np.ndarray, x2: np.ndarray, th: float, z_scale: float,
) -> int:
  """Port of isaline5.m: are two components one track?

  Returns 0 (not collinear), 1 (collinear but too far apart), 2
  (collinear but overlapping) or 3 (one track).
  """
  if x1.shape[0] == 1 and x2.shape[0] == 1:
    d = np.linalg.norm(scale_z(x1 - x2, z_scale))
    return 3 if d < _SINGLE_POINT_MAX_DIST else 0

  x = np.concatenate([x1, x2], axis=0)
  mu = x.mean(axis=0)
  _, _, vt = np.linalg.svd(x - mu, full_matrices=True)
  v = vt.T
  y = (x - mu) @ v
  if norma(y[:, 1:], 1).max() > th:
    return 0

  y1 = np.sort(((x1 - mu) @ v)[:, 0])
  y2 = np.sort(((x2 - mu) @ v)[:, 0])
  if y1[-1] < y2[0]:
    d = y2[0] - y1[-1]
  elif y2[-1] < y1[0]:
    d = y1[0] - y2[-1]
  else:
    return 2

  gaps = np.concatenate([np.diff(y1), np.diff(y2)])
  # MATLAB's mean of an empty vector is NaN and `d > NaN` is false,
  # so a one-point component always falls through to "one track".
  if gaps.size and d > _GAP_FACTOR * gaps.mean():
    return 1
  return 3


def min_distance_to_lineseg(
  lseg: np.ndarray, x: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
  """Port of mindistance_tolineseg.m for a single segment.

  ``lseg`` is (2, 3): start then end. Returns the along-axis
  coordinate measured from the start (which may be negative or exceed
  the length), the perpendicular distance, and the segment length.
  """
  du = lseg[1] - lseg[0]
  length = float(np.linalg.norm(du))
  du = du / length
  el = x @ du - lseg[0] @ du
  x0 = el[:, None] * du + lseg[0]
  return el, norma(x - x0, 1), length


def segments_from_membership(
  x: np.ndarray, e: np.ndarray, th: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
  """Port of the L2lseg subfunction of detectlseg_smallregion.m.

  Fits each column of the membership matrix ``e`` with a line and
  returns its extent as a (2, 3, M) segment array, plus the centroids
  and principal-axis frames. A column whose largest perpendicular
  residual reaches ``th`` is rejected and left as NaN, as are columns
  holding one point or none.
  """
  m = e.shape[1]
  lseg = np.full((2, 3, m), np.nan)
  mu = np.full((m, 3), np.nan)
  v = np.full((3, 3, m), np.nan)
  for i in range(m):
    ind = np.flatnonzero(e[:, i])
    if ind.size <= 1:
      continue
    x1 = x[ind]
    mu_i = x1.mean(axis=0)
    _, _, vt = np.linalg.svd(x1 - mu_i, full_matrices=True)
    v_i = vt.T
    y = (x1 - mu_i) @ v_i
    if norma(y[:, 1:], 1).max() < th:
      lo = y[np.argmin(y[:, 0]), 0]
      hi = y[np.argmax(y[:, 0]), 0]
      ends = np.array([[lo, 0.0, 0.0], [hi, 0.0, 0.0]])
      lseg[:, :, i] = ends @ v_i.T + mu_i
      mu[i] = mu_i
      v[:, :, i] = v_i
  return lseg, mu, v


def membership_from_segments(
  x: np.ndarray, lseg: np.ndarray, th: float, lth: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
  """Port of the lseg2L subfunction of detectlseg_smallregion.m.

  ``th`` bounds the perpendicular distance and ``lth`` the along-axis
  overshoot; since ``lth`` is tiny, overshooting a segment's end is
  penalised by the ratio ``th / lth`` and effectively excludes the
  point. Vectorised over segments -- the MATLAB loop is a hot spot
  because this is called once per candidate endpoint shift.

  NaN segments (rejected fits) compare false everywhere and therefore
  claim no points, which is what the MATLAB version does too.
  """
  n = x.shape[0]
  m = lseg.shape[2]
  if m == 0:
    return (np.zeros(n, dtype=np.int64), np.zeros((n, 0), dtype=bool),
            np.zeros((n, 0)))

  p0 = lseg[0].T
  du = lseg[1].T - p0
  length = norma(du, 1)
  with np.errstate(invalid="ignore", divide="ignore"):
    du = du / length[:, None]
    el = x @ du.T - np.sum(p0 * du, axis=1)
    x0 = p0[None, :, :] + el[:, :, None] * du[None, :, :]
    er = norma(x[:, None, :] - x0, 2)

    # Per-hit copy of the segment lengths, so the masked selections
    # below stay aligned once they flatten to 1-D.
    lengths = np.broadcast_to(length, (n, m))
    d = np.full((n, m), np.inf)
    inside = (el >= 0) & (el <= lengths)
    d[inside] = er[inside]
    before = el < 0
    d[before] = np.hypot(er[before], el[before] * (th / lth))
    after = el > lengths
    d[after] = np.hypot(
      er[after], (el[after] - lengths[after]) * (th / lth))

  e = d < th
  lab = np.argmin(d, axis=1) + 1
  lab[d.min(axis=1) > th] = 0
  return lab, e, d
