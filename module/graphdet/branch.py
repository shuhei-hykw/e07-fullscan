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

from .config import MATLAB_CONFIG, DetectorConfig
from .geom import min_distance_to_polyline, scale_z

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
  """
  n, m = x.shape[0], len(polylines)
  codes = np.zeros((n, m), dtype=np.uint8)
  for i, poly in enumerate(polylines):
    ell, err, _, lpoly = min_distance_to_polyline(poly, x)
    near = err < cfg.attach_max_dist
    body = (near & (ell >= cfg.end_margin)
            & (ell <= lpoly - cfg.end_margin))
    ends = near & (
      ((ell < cfg.end_margin) & (ell > -cfg.end_reach))
      | ((ell > lpoly - cfg.end_margin) & (ell < lpoly + cfg.end_reach)))
    codes[body, i] = _CODE_BODY
    codes[ends, i] = _CODE_END  # wins where both matched
  return codes


def junction_hits(codes: np.ndarray) -> np.ndarray:
  """Indices of hits that tie two or more polylines together."""
  # int64 on purpose: MATLAB sums these uint8 codes natively and would
  # saturate at 255, which happens to be harmless for a ">2" test but
  # is not something to carry over.
  return np.flatnonzero(
    codes.sum(axis=1, dtype=np.int64) > _MIN_JUNCTION_CODE_SUM)


def _components(adjacency: np.ndarray) -> np.ndarray:
  """Connected-component label per node, in first-member order.

  MATLAB gets these from ``linkage``/``cluster`` at a 0.5 cutoff over a
  0/1 distance matrix, which for single linkage (the default) is
  exactly connected components -- at O(M^3) and via a dense M x M
  distance matrix.
  """
  n = adjacency.shape[0]
  labels = np.full(n, -1, dtype=np.int64)
  label = 0
  for start in range(n):
    if labels[start] >= 0:
      continue
    stack = [start]
    labels[start] = label
    while stack:
      node = stack.pop()
      for nxt in np.flatnonzero(adjacency[node] & (labels < 0)):
        labels[nxt] = label
        stack.append(int(nxt))
    label += 1
  return labels


def branch_adjacency(polylines: list[np.ndarray], x: np.ndarray,
                     codes: np.ndarray | None = None,
                     cfg: DetectorConfig = MATLAB_CONFIG) -> np.ndarray:
  """(M, M) boolean: do these two polylines share a junction hit?"""
  if codes is None:
    codes = attachment_codes(polylines, x, cfg)
  sub = codes[junction_hits(codes)].astype(np.float64)
  adjacency = (sub.T @ sub) > 0
  np.fill_diagonal(adjacency, False)
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
  sub = codes[idx] > 0
  centroids, members = [], []
  m = len(polylines)
  for i in range(m):
    for j in range(i + 1, m):
      both = sub[:, i] & sub[:, j]
      if both.any():
        centroids.append(x[idx[both]].mean(axis=0))
        members.append({i, j})
  if not centroids:
    return np.zeros((0, 3)), np.zeros(0, dtype=np.int64)

  centroids = np.array(centroids)
  labels = _components(
    np.linalg.norm(
      scale_z(centroids[:, None, :] - centroids[None, :, :],
              cfg.z_scale),
      axis=2) < cfg.vertex_merge)
  out, mult = [], []
  for lab in range(labels.max() + 1):
    sel = np.flatnonzero(labels == lab)
    out.append(centroids[sel].mean(axis=0))
    mult.append(len(set().union(*(members[s] for s in sel))))
  return np.array(out), np.array(mult, dtype=np.int64)
