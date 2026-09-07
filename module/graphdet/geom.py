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
from scipy.spatial import cKDTree

from .config import MATLAB_CONFIG, MATLAB_Z_SCALE, DetectorConfig

# isaline5.m: a gap wider than this many times the mean point spacing
# means the two components are separate tracks. Scale-free by
# construction, so it stays out of DetectorConfig.
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
  cfg: DetectorConfig = MATLAB_CONFIG,
) -> int:
  """Port of isaline5.m: are two components one track?

  Returns 0 (not collinear), 1 (collinear but too far apart), 2
  (collinear but overlapping) or 3 (one track).
  """
  if x1.shape[0] == 1 and x2.shape[0] == 1:
    d = np.linalg.norm(scale_z(x1 - x2, z_scale))
    return 3 if d < cfg.single_point_max_dist else 0

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
  # A zero-length segment (a polyline fitted from a single hit) gives
  # NaN here, as it does in MATLAB. Callers treat a NaN distance as
  # "no match" rather than propagating it.
  with np.errstate(invalid="ignore", divide="ignore"):
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


# isaline3.m weights the along-axis gap by this before taking the
# norm, so a long collinear gap costs a tenth of the same lateral
# offset. A ratio, so it does not belong in DetectorConfig.
_JOIN_ALONG_WEIGHT = 0.1


def _colmajor_argmin(d: np.ndarray) -> tuple[int, int]:
  """(row, col) of the minimum, MATLAB's first-of-equals order.

  ``min(d,[],'all')`` scans column-major, so a tie is broken by the
  lower column first, then the lower row -- the opposite of NumPy.
  """
  flat = int(np.argmin(d.ravel(order="F")))
  return flat % d.shape[0], flat // d.shape[0]


def is_a_line3(lseg1: np.ndarray, lseg2: np.ndarray,
               cfg: DetectorConfig = MATLAB_CONFIG) -> float:
  """Port of isaline3.m: may lseg2 be joined onto lseg1's first point?

  Both segments are given "focus point first". Returns the (weighted)
  endpoint gap, or inf if the pair does not form one straight line.
  """
  v1, v2 = np.diff(lseg1, axis=0)[0], np.diff(lseg2, axis=0)[0]
  n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
  if n1 == 0 or n2 == 0:
    # A degenerate segment has no direction to be collinear with.
    # MATLAB divides by zero here and returns NaN, which its min()
    # then skips -- except when EVERY candidate is NaN, where it
    # returns index 1 and joins on a distance of NaN. Rejecting is
    # what the skipping was for.
    return np.inf
  v1, v2 = v1 / n1, v2 / n2
  if v1 @ v2 > 0:  # pointing the same way: they cannot meet head to head
    return np.inf

  # Rows 1 and 2 are the two focus endpoints; rows 0 and 3 the far ones.
  lseg = np.concatenate([lseg1[::-1], lseg2], axis=0)
  mu = lseg.mean(axis=0)
  _, _, vt = np.linalg.svd(lseg - mu, full_matrices=True)
  y = (lseg - mu) @ vt.T
  if norma(y[:, 1:], 1).max() > cfg.join_max_residual:
    return np.inf

  order = np.argsort(y[:, 0], kind="stable")
  y = y[order]
  if order[0] in (1, 2) or order[-1] in (1, 2):
    return np.inf  # a focus endpoint sticks out past a far endpoint
  ordered = (np.array_equal(order, [0, 1, 2, 3])
             or np.array_equal(order, [3, 2, 1, 0]))
  overlapping = (np.array_equal(order, [0, 2, 1, 3])
                 or np.array_equal(order, [3, 1, 2, 0]))
  if not (ordered or overlapping):
    return np.inf
  gap = np.diff(y[1:3], axis=0)[0]
  weights = np.array([_JOIN_ALONG_WEIGHT] + [1.0] * (gap.size - 1))
  return float(np.linalg.norm(gap * weights))


def is_a_line3a(lseg1: np.ndarray, lseg2: np.ndarray,
                cfg: DetectorConfig = MATLAB_CONFIG) -> float:
  """Port of isaline3a.m: may two polylines be joined end to end?

  Each argument is the two-point stub at the end being joined, focus
  point first. Unlike isaline3 the return value is the kink ANGLE in
  degrees, not a distance -- integrate_smallregions thresholds the two
  differently.
  """
  d = np.linalg.norm(lseg1[:, None, :] - lseg2[None, :, :], axis=2)
  if _colmajor_argmin(d) != (0, 0):
    return np.inf  # some other endpoint pair is closer

  v1, v2 = np.diff(lseg1, axis=0)[0], np.diff(lseg2, axis=0)[0]
  n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
  if n1 == 0 or n2 == 0:
    return np.inf
  v1, v2 = v1 / n1, v2 / n2
  if v1 @ v2 > 0:
    return np.inf

  lseg = np.concatenate([lseg1[::-1], lseg2], axis=0)
  mu = lseg.mean(axis=0)
  _, _, vt = np.linalg.svd(lseg - mu, full_matrices=True)
  y = (lseg - mu) @ vt[0]
  if y[0] > y[-1]:
    y = y[::-1]
  if y[2] - y[1] < -cfg.join_max_overlap:
    return np.inf

  # Bend both stubs to the midpoint of the two focus endpoints and ask
  # how far each had to move; a real junction moves neither much.
  mid = 0.5 * (lseg1[0] + lseg2[0])
  _, er1, _ = min_distance_to_lineseg(
    np.stack([mid, lseg1[1]]), lseg1[None, 0])
  _, er2, _ = min_distance_to_lineseg(
    np.stack([mid, lseg2[1]]), lseg2[None, 0])
  if er1[0] + er2[0] > cfg.join_max_kink:
    return np.inf

  u1, u2 = mid - lseg1[1], mid - lseg2[1]
  n1, n2 = np.linalg.norm(u1), np.linalg.norm(u2)
  if n1 == 0 or n2 == 0:
    return np.inf
  return float(np.degrees(np.arccos(
    np.clip(-((u1 / n1) @ (u2 / n2)), -1.0, 1.0))))


# mindistance_to_polyline.m calls two segments equidistant within this.
_POLY_TIE_TOL = 1e-6


def min_distance_to_polyline(
  polyline: np.ndarray, x: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
  """Port of mindistance_to_polyline.m.

  Returns, per point: the arc length along the polyline measured from
  its start, the perpendicular distance, the 0-based index of the
  closest segment, and the polyline's total length. Points beyond
  either end are measured against the extension of the first/last
  segment, so the arc length may be negative or exceed the length.
  """
  dim = polyline.shape[1]
  n, k = x.shape[0], polyline.shape[0] - 1
  el0 = np.concatenate([[0.0], np.cumsum(norma(np.diff(polyline, axis=0), 1))])
  lpoly = float(el0[-1])
  el = np.zeros((n, k))
  er = np.zeros((n, k))
  elover = np.zeros((n, k))
  for i in range(k):
    e, r, seg_len = min_distance_to_lineseg(polyline[i:i + 2], x[:, :dim])
    elover[:, i] = np.abs(e - np.clip(e, 0.0, seg_len))
    if i > 0:  # only the first segment may be extended backwards
      m = e < 0
      r = np.where(m, np.hypot(r, e), r)
      e = np.where(m, 0.0, e)
    if i < k - 1:  # only the last segment may be extended forwards
      m = e > seg_len
      r = np.where(m, np.hypot(r, e - seg_len), r)
      e = np.where(m, seg_len, e)
    el[:, i], er[:, i] = e, r

  # MATLAB's min skips NaN, which a zero-length segment produces.
  # An all-inf row then makes the tie test inf - inf; the NaN that
  # falls out compares false, which is the answer we want anyway.
  with np.errstate(invalid="ignore"):
    er_cmp = np.where(np.isnan(er), np.inf, er)
    c = er_cmp.argmin(axis=1)
    err = er_cmp[np.arange(n), c]
    # Among segments the point is equally far from, prefer the one it
    # does not overshoot -- otherwise a shared vertex would be
    # credited to whichever segment happened to come first.
    tied = (np.abs(er_cmp - err[:, None]) < _POLY_TIE_TOL).sum(axis=1) > 1
  if tied.any():
    c[tied] = elover[tied].argmin(axis=1)
  ell = (el + el0[:-1])[np.arange(n), c]
  return ell, err, c, lpoly


def hits_near_polyline(
  tree: cKDTree, poly: np.ndarray, reach: float, end_reach: float = 0.0,
) -> np.ndarray:
  """Hits that could lie within ``reach`` of a polyline, ascending.

  Both callers ask which hits a polyline claims, and both used to scan
  every hit in the view for every polyline: fine for a simulation's
  41,609 hits and 175 polylines, hours for a real E07 tile's 240,824
  and ~10,000. A hit within ``reach`` of the curve is within
  ``half-length + reach`` of some segment's midpoint, so a ball query
  per segment is a superset of the answer and the exact test still
  runs on what comes back. ``end_reach`` extends the query past the
  two ends, for callers that count hits beyond them.
  """
  mid = 0.5 * (poly[:-1] + poly[1:])
  half = 0.5 * norma(np.diff(poly, axis=0), 1)
  found: set = set()
  for m, h in zip(mid, half):
    found.update(tree.query_ball_point(m, h + reach))
  if end_reach > 0.0:
    for end in (poly[0], poly[-1]):
      found.update(tree.query_ball_point(end, end_reach))
  if not found:
    return np.zeros(0, dtype=np.int64)
  return np.sort(np.fromiter(found, dtype=np.int64, count=len(found)))
