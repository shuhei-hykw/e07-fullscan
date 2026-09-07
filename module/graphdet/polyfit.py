"""Port of pixellist2poly.m: fit an ordered hit list with a polyline.

Only the ``flag=1`` branch is ported -- the caller
(``integrate_smallregions``) has already ordered the hits along the
track, and the ``flag=2/3`` branches reorder them with a minimum
spanning tree over an all-pairs distance matrix, which no production
path takes and which would not scale to a full view anyway.

The fit is a binary search, not a sweep: starting from the whole list
it halves the window until the straight-line residual first crosses
the threshold, which is where the track bends. That node becomes a
polyline vertex and the search restarts from it.
"""
from __future__ import annotations

import numpy as np

from .geom import (
  _colmajor_argmin, min_distance_to_polyline, norma,
)

_DEFAULT_DIM = 3
_DEFAULT_TH = 1.5


def _round_half_up(value: float) -> int:
  """MATLAB's round(): halves go away from zero, not to even."""
  return int(np.floor(value + 0.5))


def _max_residual(x: np.ndarray, dim: int) -> float:
  """Largest distance from a point to the best-fit line through them."""
  if x.shape[0] < dim:
    return 0.0  # too few points to be anything but collinear
  mu = x.mean(axis=0)
  _, _, vt = np.linalg.svd(x - mu, full_matrices=True)
  y = (x - mu) @ vt.T
  return float(norma(y[:, 1:dim], 1).max())


def inflection_nodes(x: np.ndarray, dim: int, th: float) -> list[int]:
  """Port of pixellist2poly.m's subfunc1: 1-based bend node numbers.

  Indices are 1-based because the surrounding MATLAB slicing is
  inclusive on both ends; converting here would make the halving
  arithmetic harder to check against the original.
  """
  n = x.shape[0]
  q: list[int] = []
  i = h = 1
  j = k = n
  while True:
    while True:
      if _max_residual(x[i - 1:j, :dim], dim) > th:
        if j - h <= 1:
          p = h
          break
        k, j = j, (h + j + 1) // 2
      else:
        if k - j <= 1:
          p = j
          break
        h, j = j, (j + k + 1) // 2
    if p == n:
      break
    q.append(p)
    if p == n - 1:
      break
    i = h = p
    j = k = n
  return q


def _fit_segment(x: np.ndarray, dim: int) -> np.ndarray:
  """Extent of the best-fit line through x, as a (2, dim) segment.

  Oriented so that it runs from the first hit towards the last.
  """
  x = x[:, :dim]
  mu = x.mean(axis=0)
  _, _, vt = np.linalg.svd(x - mu, full_matrices=True)
  v = vt.T
  if (x[-1] - x[0]) @ v[:, 0] < 0:
    v = -v
  y = (x - mu) @ v
  ends = np.zeros((2, dim))
  ends[0, 0], ends[1, 0] = y[:, 0].min(), y[:, 0].max()
  return ends @ v.T + mu


def polyline_from_nodes(
  x: np.ndarray, q: list[int], dim: int,
) -> tuple[np.ndarray, np.ndarray]:
  """Port of subfunc2: fit one segment between consecutive bend nodes.

  Adjacent segments are flipped so they run head to tail, and each
  shared vertex is placed at the midpoint of the two fits rather than
  at their intersection -- cheaper, and the two ends are within the
  residual threshold of each other by construction.
  """
  if not q:
    return _fit_segment(x, dim), np.empty(0)

  nodes = [1] + list(q) + [x.shape[0]]
  n = len(nodes) - 1
  lseg = np.zeros((2, dim, n))
  for i in range(n):
    lseg[:, :, i] = _fit_segment(x[nodes[i] - 1:nodes[i + 1]], dim)

  for i in range(n - 1):
    d = np.linalg.norm(
      lseg[:, None, :, i] - lseg[None, :, :, i + 1], axis=2)
    node1, node2 = _colmajor_argmin(d)
    if i == 0 and node1 == 0:
      lseg[:, :, i] = lseg[::-1, :, i]
    if node2 == 1:
      lseg[:, :, i + 1] = lseg[::-1, :, i + 1]

  poly = np.zeros((n + 1, dim))
  poly[0] = lseg[0, :, 0]
  for i in range(1, n):
    poly[i] = 0.5 * (lseg[1, :, i - 1] + lseg[0, :, i])
  poly[-1] = lseg[1, :, n - 1]

  d = np.diff(poly, axis=0)
  d = d / norma(d, 1)[:, None]
  cos = np.clip((d[:-1] * d[1:]).sum(axis=1), -1.0, 1.0)
  return poly, np.degrees(np.arccos(cos))


def pixellist_to_poly(
  x: np.ndarray, dim: int = _DEFAULT_DIM, th: float = _DEFAULT_TH,
):
  """Port of pixellist2poly.m (flag=1).

  Returns (polyline, bend node indices (0-based), turn angles in
  degrees, closest-segment index per hit, per-hit residual, total
  polyline length).
  """
  nodes = inflection_nodes(x, dim, th)
  poly, dth = polyline_from_nodes(x, nodes, dim)
  _, er, c, lpoly = min_distance_to_polyline(poly, x[:, :dim])
  return poly, np.array(nodes, dtype=np.int64) - 1, dth, c, er, lpoly
