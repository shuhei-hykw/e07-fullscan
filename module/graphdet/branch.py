"""Port of detectbunki.m: group tracks that branch from a common point.

A hit near the middle of one polyline and near the END of another is
evidence that the second track starts where the first passes -- a
branch. detectbunki collects such hits, links every pair of polylines
that share one, and returns the connected components, largest first.

``branch_points`` is not part of the MATLAB original. detectbunki
returns groups, never vertex coordinates, but the coordinates are what
the E07 analysis is after, so they are derived here from the same
shared hits the grouping already found.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from .config import MATLAB_CONFIG, DetectorConfig
from .geom import hits_near_polyline, min_distance_to_polyline, scale_z

_CODE_BODY = 1
_CODE_END = 2
# A hit joins two polylines only if its codes add to more than this,
# i.e. it is at one polyline's end and on another's body (1 + 2), or
# at the ends of two (2 + 2), or on the body of three. Two bodies
# crossing (1 + 1) is just a crossing, not a branch.
_MIN_JUNCTION_CODE_SUM = 2


def attachment_codes(
  polylines: list[np.ndarray], x: np.ndarray,
  cfg: DetectorConfig = MATLAB_CONFIG,
) -> np.ndarray:
  """(N, M) uint8 matrix: how each hit attaches to each polyline.

  0 = not attached, _CODE_BODY = near the middle, _CODE_END = near (or
  just past) one end.

  Sparse on purpose. A hit touches a handful of polylines at most, but
  a real E07 tile has ~29,000 polylines over ~241,000 hits and the
  dense matrix would be 7 GB -- more than any kekcc queue allows.
  """
  n, m = x.shape[0], len(polylines)
  rows: list[np.ndarray] = []
  cols: list[np.ndarray] = []
  vals: list[np.ndarray] = []
  tree = cKDTree(x)
  reach = cfg.attach_max_dist
  end_reach = cfg.end_reach + reach
  for i, poly in enumerate(polylines):
    cand = hits_near_polyline(tree, poly, reach, end_reach)
    if cand.size == 0:
      continue
    ell, err, _, lpoly = min_distance_to_polyline(poly, x[cand])
    near = err < cfg.attach_max_dist
    body = (near & (ell >= cfg.end_margin)
            & (ell <= lpoly - cfg.end_margin))
    ends = near & (
      ((ell < cfg.end_margin) & (ell > -cfg.end_reach))
      | ((ell > lpoly - cfg.end_margin) & (ell < lpoly + cfg.end_reach)))
    # _CODE_END wins where both matched, so body entries that are also
    # ends are dropped rather than summed.
    body &= ~ends
    for mask, code in ((body, _CODE_BODY), (ends, _CODE_END)):
      if mask.any():
        rows.append(cand[mask])
        cols.append(np.full(int(mask.sum()), i, dtype=np.int64))
        vals.append(np.full(int(mask.sum()), code, dtype=np.uint8))
  if not rows:
    return csr_matrix((n, m), dtype=np.uint8)
  return coo_matrix(
    (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
    shape=(n, m), dtype=np.uint8).tocsr()


def junction_hits(codes) -> np.ndarray:
  """Indices of hits that tie two or more polylines together."""
  # int64 on purpose: MATLAB sums these uint8 codes natively and would
  # saturate at 255, which happens to be harmless for a ">2" test but
  # is not something to carry over.
  total = np.asarray(
    codes.astype(np.int64).sum(axis=1)).ravel()
  return np.flatnonzero(total > _MIN_JUNCTION_CODE_SUM)


def _components(adjacency) -> np.ndarray:
  """Connected-component label per node, in first-member order.

  MATLAB gets these from ``linkage``/``cluster`` at a 0.5 cutoff over a
  0/1 distance matrix, which for single linkage (the default) is
  exactly connected components -- at O(M^3) and via a dense M x M
  distance matrix.

  Labels are renumbered by first member so the result does not depend
  on SciPy's traversal order.
  """
  if not hasattr(adjacency, "tocsr"):
    adjacency = csr_matrix(np.asarray(adjacency))
  _, raw = connected_components(adjacency, directed=False)
  order = np.full(raw.max() + 1 if raw.size else 0, -1, dtype=np.int64)
  labels = np.empty(raw.size, dtype=np.int64)
  nxt = 0
  for i, r in enumerate(raw):
    if order[r] < 0:
      order[r] = nxt
      nxt += 1
    labels[i] = order[r]
  return labels


def branch_adjacency(polylines: list[np.ndarray], x: np.ndarray,
                     codes=None,
                     cfg: DetectorConfig = MATLAB_CONFIG):
  """Sparse (M, M): do these two polylines share a junction hit?"""
  if codes is None:
    codes = attachment_codes(polylines, x, cfg)
  sub = csr_matrix(codes)[junction_hits(codes)]
  sub.data = np.ones_like(sub.data)
  adjacency = (sub.T @ sub).tocsr()
  adjacency.setdiag(0)
  adjacency.eliminate_zeros()
  return adjacency


def detect_branches(
  polylines: list[np.ndarray], x: np.ndarray,
  codes: np.ndarray | None = None,
  cfg: DetectorConfig = MATLAB_CONFIG,
) -> tuple[list[np.ndarray], np.ndarray]:
  """Port of detectbunki.m.

  Returns the polylines regrouped so that branching tracks are
  adjacent, largest group first, and a 1-based group id per polyline.
  """
  if not polylines:
    return [], np.zeros(0, dtype=np.int64)
  if codes is None:
    codes = attachment_codes(polylines, x, cfg)
  labels = _components(branch_adjacency(polylines, x, codes, cfg))
  sizes = np.bincount(labels)
  regrouped: list[np.ndarray] = []
  ids: list[int] = []
  for gid, comp in enumerate(np.argsort(-sizes, kind="stable"), start=1):
    members = np.flatnonzero(labels == comp)
    regrouped.extend(polylines[i] for i in members)
    ids.extend([gid] * members.size)
  return regrouped, np.array(ids, dtype=np.int64)


def branch_points(
  polylines: list[np.ndarray], x: np.ndarray,
  codes: np.ndarray | None = None,
  cfg: DetectorConfig = MATLAB_CONFIG,
) -> tuple[np.ndarray, np.ndarray]:
  """Vertex coordinates implied by the grouping (NOT in the original).

  Every pair of polylines that share junction hits contributes the
  centroid of those hits; centroids describing the same vertex are
  then merged. Returns the (V, 3) coordinates and the number of
  polylines meeting at each -- the reconstructed analogue of the true
  branch points recorded in ``simdata8.mat``'s ``Summary``.
  """
  if codes is None:
    codes = attachment_codes(polylines, x, cfg)
  idx = junction_hits(codes)
  if idx.size == 0:
    return np.zeros((0, 3)), np.zeros(0, dtype=np.int64)
  # Walk the junction hits rather than all M^2 polyline pairs: a hit
  # ties a handful of polylines together, so this is O(H * k^2) with a
  # tiny k, where the pair loop was 840 million iterations on a real
  # E07 tile.
  sub = csr_matrix(codes)[idx]
  shared: dict = {}
  for h in range(idx.size):
    attached = sub.indices[sub.indptr[h]:sub.indptr[h + 1]]
    for a in range(attached.size):
      for b in range(a + 1, attached.size):
        key = (int(attached[a]), int(attached[b]))
        shared.setdefault(key, []).append(idx[h])
  if not shared:
    return np.zeros((0, 3)), np.zeros(0, dtype=np.int64)
  keys = sorted(shared)
  centroids = np.array([x[shared[k]].mean(axis=0) for k in keys])
  members = [set(k) for k in keys]
  # Merging by an all-pairs distance matrix needs a (P, P, 3)
  # intermediate, which on a dense tile is tens of GB and killed a
  # batch job at the 4 GB cap. A radius query builds the same graph.
  scaled = scale_z(centroids, cfg.z_scale)
  tree = cKDTree(scaled)
  pairs = np.asarray(sorted(tree.query_pairs(cfg.vertex_merge)),
                     dtype=np.int64).reshape(-1, 2)
  if pairs.size:
    pairs = pairs[np.linalg.norm(
      scaled[pairs[:, 0]] - scaled[pairs[:, 1]], axis=1)
      < cfg.vertex_merge]
  n_c = centroids.shape[0]
  labels = _components(coo_matrix(
    (np.ones(pairs.shape[0] * 2, dtype=np.uint8),
     (np.concatenate([pairs[:, 0], pairs[:, 1]]),
      np.concatenate([pairs[:, 1], pairs[:, 0]]))),
    shape=(n_c, n_c)).tocsr())
  out, mult = [], []
  for lab in range(labels.max() + 1):
    sel = np.flatnonzero(labels == lab)
    out.append(centroids[sel].mean(axis=0))
    mult.append(len(set().union(*(members[s] for s in sel))))
  return np.array(out), np.array(mult, dtype=np.int64)
