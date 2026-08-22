"""Port of detectlseg_smallregion.m: hit points -> 3-D line segments.

Stage 1 of the MATLAB graph track detector (``e07/matlab``). Works on
one 128 x 128 x 80 sub-region at a time and returns the straight
segments it can support, as a (2, 3, M) array of endpoint pairs.

Two steps, matching the MATLAB subfunctions:

1. ``split_into_linear_components`` builds a minimum spanning tree over
   the hits and cuts its heaviest edge inside any component that is not
   straight, until every component is. Edges cut in the process are
   then offered back: two components that turn out to be collinear,
   adjacent and non-overlapping are rejoined.
2. ``grow_segments`` lets each component claim every hit near its own
   principal axis -- hits may be claimed by several components at once,
   which is what lets crossing tracks keep their shared pixels -- then
   merges components that end up describing the same hits and drops
   ones fully contained in others. ``refine_endpoints`` finally slides
   each endpoint to the position that leaves the fewest hits claimed by
   anything other than exactly one segment.

The MATLAB constants are reproduced as defaults so the port can be
checked against ``e07/matlab/work1.mat``; every one of them was tuned
on a simulation with 159 tracks per view and ~3 px spacing along a
track, so they are expected to need retuning for E07 data.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import minimum_spanning_tree
from scipy.spatial.distance import pdist, squareform

from .geom import (
  MATLAB_Z_SCALE, is_a_line, is_same_track, membership_from_segments,
  norma, scale_z, segments_from_membership,
)

# Straightness tolerance when cutting the spanning tree (subfunc1) and
# when growing segments (subfunc2). MATLAB calls these TH.
TH_SPLIT = 2.0
TH_GROW = 1.5

# A component needs this many hits before a line is fitted to it;
# below it, the component claims exactly its own hits.
_MIN_FIT_POINTS = 3

# How far past its own extent a component looks for more hits, in px.
_GROW_MARGIN = 20.0

# Merge component i into j when this fraction of i's hits are also j's;
# drop i outright when this fraction are claimed by any other segment.
_MERGE_FRAC = 0.65
_DROP_FRAC = 0.8

# Endpoint refinement: candidate shifts, and the fit tolerance used to
# turn memberships back into segments while refining.
_REFINE_PASSES = 10
_REFINE_DL = 20.0
_REFINE_DL_STEP = 5.0
_REFINE_DL_MIN = 2.0
_REFINE_FIT_TH = 10.0
# Along-axis tolerance for lseg2L. Tiny on purpose: overshooting an
# endpoint is penalised by TH / this ratio, which excludes the hit.
_ALONG_TOL = 1e-5

# Sub-region geometry from detect_tracks.m.
REGION_PX = 128
REGION_Z = 80
N_REGIONS = 16


def _conncomp(
  n: int, edges: np.ndarray, alive: np.ndarray,
) -> tuple[np.ndarray, int]:
  """Connected components, labelled 1..M in MATLAB's conncomp order.

  MATLAB numbers components by first appearance when scanning nodes in
  index order; the labels feed a stable sort later, so the convention
  has to match.
  """
  parent = np.arange(n)

  def find(a: int) -> int:
    while parent[a] != a:
      parent[a] = parent[parent[a]]
      a = parent[a]
    return a

  for u, v in edges[alive]:
    ru, rv = find(int(u)), find(int(v))
    if ru != rv:
      parent[ru] = rv

  lab = np.empty(n, dtype=np.int64)
  seen: dict[int, int] = {}
  for i in range(n):
    r = find(i)
    if r not in seen:
      seen[r] = len(seen) + 1
    lab[i] = seen[r]
  return lab, len(seen)


def split_into_linear_components(
  x: np.ndarray, th: float = TH_SPLIT,
  z_scale: float = MATLAB_Z_SCALE,
) -> np.ndarray:
  """Port of subfunc1: cut a spanning tree until every part is straight.

  Returns a 1-based label per hit, renumbered so that label 1 is the
  component holding the most hits.
  """
  n = x.shape[0]
  if n == 1:
    return np.ones(1, dtype=np.int64)

  dm = squareform(pdist(scale_z(x, z_scale)))
  if np.any(dm[np.triu_indices(n, 1)] == 0.0):
    raise ValueError(
      "coincident hits: MATLAB's graph() drops zero-weight edges, so "
      "the spanning tree would not be comparable")
  coo = minimum_spanning_tree(csr_matrix(dm)).tocoo()
  eu = np.minimum(coo.row, coo.col)
  ev = np.maximum(coo.row, coo.col)
  # MATLAB keeps a graph's Edges table sorted by node pair; the cut
  # below takes the first of equal weights, so the order matters.
  order = np.lexsort((ev, eu))
  edges = np.column_stack([eu[order], ev[order]])
  weights = coo.data[order]
  alive = np.ones(weights.size, dtype=bool)

  removed: list[int] = []
  linear: dict[bytes, bool] = {}
  while True:
    lab, m = _conncomp(n, edges, alive)
    cut = False
    # One cut per component per pass, all judged against the labels
    # from the top of the pass, exactly as the MATLAB loop does.
    for i in range(1, m + 1):
      nodes = np.flatnonzero(lab == i)
      key = nodes.tobytes()
      if key not in linear:
        linear[key] = is_a_line(x[nodes], th)
      if linear[key]:
        continue
      inside = np.flatnonzero(
        alive & np.isin(edges[:, 0], nodes)
        & np.isin(edges[:, 1], nodes))
      pick = int(inside[np.argmax(weights[inside])])
      alive[pick] = False
      removed.append(pick)
      cut = True
    if not cut:
      break

  # Offer the cut edges back, in the order they were cut. Labels are
  # merged as we go, so a later revival sees the earlier ones.
  revived = []
  for idx in removed:
    u, v = edges[idx]
    lu = lab[u]
    ind1 = lab == lu
    ind2 = lab == lab[v]
    if is_same_track(x[ind1], x[ind2], th, z_scale) == 3:
      lab[ind2] = lu
      revived.append(idx)
  if revived:
    alive[revived] = True
    lab, m = _conncomp(n, edges, alive)

  counts = np.bincount(lab, minlength=m + 1)[1:]
  order = np.argsort(-counts, kind="stable")
  rank = np.empty(m, dtype=np.int64)
  rank[order] = np.arange(1, m + 1)
  return rank[lab - 1]


def _merge_overlapping(e: np.ndarray) -> np.ndarray:
  """Collapse segments describing the same hits (inner loop of subfunc2)."""
  m = e.shape[1]
  ef = e.astype(np.float64)
  while True:
    sizes = np.maximum(e.sum(axis=0), 1).astype(np.float64)
    u = (ef.T @ ef) / sizes[:, None]
    np.fill_diagonal(u, 0.0)
    # MATLAB's max(U, [], 'all') returns the first maximum in
    # column-major order.
    flat = int(np.argmax(u.ravel(order="F")))
    ui, uj = flat % m, flat // m
    if u[ui, uj] > _MERGE_FRAC:
      e[:, uj] = e[:, ui] | e[:, uj]
      e[:, ui] = False
      ef = e.astype(np.float64)
      continue

    shared = np.zeros(m)
    for i in range(m):
      others = np.ones(m, dtype=bool)
      others[i] = False
      shared[i] = np.count_nonzero(e[:, i] & e[:, others].any(axis=1))
    shared /= sizes
    k = int(np.argmax(shared))
    if shared[k] > _DROP_FRAC:
      e[:, k] = False
      ef = e.astype(np.float64)
    else:
      return e


def grow_segments(
  x: np.ndarray, labels: np.ndarray, th: float = TH_GROW,
) -> np.ndarray:
  """Port of subfunc2: let each component absorb nearby collinear hits.

  Returns the membership matrix: (N, M) booleans, one column per
  surviving segment. A hit may belong to more than one column.
  """
  n = x.shape[0]
  m = int(labels.max())
  e = np.zeros((n, m), dtype=bool)
  for i in range(m):
    e[labels == i + 1, i] = True

  # Allocated once: MATLAB reuses this buffer across iterations and
  # only overwrites the rows within a segment's reach, so rows outside
  # it keep the previous iteration's values.
  d = np.full((n, m), np.inf)
  while True:
    counts = e.sum(axis=0)
    for i in range(m):
      ind = e[:, i]
      if counts[i] < _MIN_FIT_POINTS:
        d[ind, i] = 0.0
        d[~ind, i] = np.inf
        continue
      x1 = x[ind]
      mu = x1.mean(axis=0)
      _, _, vt = np.linalg.svd(x1 - mu, full_matrices=True)
      y = (x - mu) @ vt.T
      along = np.sort(y[ind, 0])
      sel = ((along[0] - _GROW_MARGIN < y[:, 0])
             & (y[:, 0] < along[-1] + _GROW_MARGIN))
      d[sel, i] = norma(y[sel, 1:], 1)
    old_e = e
    e = _merge_overlapping(d < th)
    if np.array_equal(e, old_e):
      break

  return e[:, e.sum(axis=0) > 1]


def refine_endpoints(
  x: np.ndarray, e: np.ndarray, th: float = TH_GROW,
) -> np.ndarray:
  """Port of the endpoint tuning loop at the end of subfunc2.

  Slides each endpoint along its own segment, keeping the shift that
  leaves the fewest hits claimed by other than exactly one segment.
  Shrinks the step once a pass changes nothing.
  """
  dl = np.arange(-_REFINE_DL, _REFINE_DL + _REFINE_DL_STEP / 2,
                 _REFINE_DL_STEP)
  lseg = np.zeros((2, 3, 0))
  for _ in range(_REFINE_PASSES):
    lseg, _, _ = segments_from_membership(x, e, _REFINE_FIT_TH)
    moved = False
    for i in range(lseg.shape[2]):
      if np.isnan(lseg[:, :, i]).any():
        continue
      for j in range(2):
        dv = lseg[j, :, i] - lseg[1 - j, :, i]
        dv = dv / np.linalg.norm(dv)
        lseg2 = lseg.copy()
        err = np.zeros(dl.size)
        for k in range(dl.size):
          lseg2[j, :, i] = lseg[j, :, i] + dv * dl[k]
          _, e, _ = membership_from_segments(x, lseg2, th, _ALONG_TOL)
          err[k] = np.count_nonzero(e.sum(axis=1) != 1)
        k = int(np.argmin(err))
        lseg[j, :, i] = lseg[j, :, i] + dv * dl[k]
        if dl[k] != 0:
          moved = True
    if not moved:
      dl = dl / 2
    if dl[-1] < _REFINE_DL_MIN:
      break

  return lseg[:, :, ~np.isnan(lseg[0, 0, :])]


def detect_lseg_smallregion(
  x: np.ndarray, *, th_split: float = TH_SPLIT, th_grow: float = TH_GROW,
  z_scale: float = MATLAB_Z_SCALE,
) -> np.ndarray:
  """Detect line segments in one sub-region. Returns (2, 3, M)."""
  if x.shape[0] == 0:
    return np.zeros((2, 3, 0))
  labels = split_into_linear_components(x, th_split, z_scale)
  e = grow_segments(x, labels, th_grow)
  return refine_endpoints(x, e, th_grow)


def iter_regions(
  x: np.ndarray, *, region_px: int = REGION_PX,
  region_z: int = REGION_Z, n_regions: int = N_REGIONS,
):
  """Yield (index, lower bound, hits) per sub-region, in MATLAB order.

  detect_tracks.m walks a 16 x 16 grid with the fast index on x, and
  takes hits with lb < p <= ub so that neighbouring regions do not
  share a boundary hit.
  """
  rg = np.linspace(0.0, float(region_px * n_regions), n_regions + 1)
  for k in range(n_regions * n_regions):
    a, b = divmod(k, n_regions)
    lb = np.array([rg[b], rg[a], 0.0])
    ub = np.array([rg[b + 1], rg[a + 1], float(region_z)])
    sel = np.all((x > lb) & (x <= ub), axis=1)
    yield k, lb, x[sel] - lb


def detect_lseg_view(
  x: np.ndarray, *, region_px: int = REGION_PX, region_z: int = REGION_Z,
  n_regions: int = N_REGIONS, progress=None, **kwargs,
) -> tuple[np.ndarray, np.ndarray]:
  """Run every sub-region of one view. Returns (segments, per-region count).

  Segments come back in region order and in view coordinates, matching
  how detect_tracks.m concatenates its parfor results.
  """
  out, counts = [], []
  for k, lb, x1 in iter_regions(
      x, region_px=region_px, region_z=region_z, n_regions=n_regions):
    seg = detect_lseg_smallregion(x1, **kwargs)
    counts.append(seg.shape[2])
    if seg.shape[2]:
      out.append(seg + lb[None, :, None])
    if progress is not None:
      progress(k, x1.shape[0], seg.shape[2])
  segments = (np.concatenate(out, axis=2) if out
              else np.zeros((2, 3, 0)))
  return segments, np.array(counts)
