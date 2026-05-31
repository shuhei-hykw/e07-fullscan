"""Cross-slice track linking: connect 2D segments into 3D tracks."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ._cluster import _angle_diff

if TYPE_CHECKING:
  import pandas as pd

_MAX_DIST   = 30.0  # max midpoint distance between adjacent slices (px)
_ANGLE_EPS  = 5.0   # max angle difference (deg)
_INTENS_EPS = 0.5   # max relative intensity difference (0–1; 0 = disabled)
_WIDTH_EPS  = 0.5   # max relative width difference   (0–1; 0 = disabled)


def _midpoints(sub: "pd.DataFrame") -> np.ndarray:
  mx = (sub["px1"].to_numpy() + sub["px2"].to_numpy()) / 2.0
  my = (sub["py1"].to_numpy() + sub["py2"].to_numpy()) / 2.0
  return np.column_stack([mx, my])


def _match_slice_pair(
  cur, nxt, union, *,
  max_dist: float,
  angle_eps: float,
  intens_eps: float,
  width_eps: float,
  cur_pts: np.ndarray,
  nxt_pts: np.ndarray,
) -> None:
  """Apply mutual-NN matching between two slice sub-DataFrames.

    *cur_pts* and *nxt_pts* are (N,2) midpoint arrays in whatever
    coordinate space the caller chooses (pixel or mm).  *max_dist*
    must be in the same unit.
    """
  cur_ix  = cur.index.to_numpy()
  nxt_ix  = nxt.index.to_numpy()
  cur_ang = cur["angle_deg"].to_numpy()
  nxt_ang = nxt["angle_deg"].to_numpy()

  has_intens = intens_eps > 0 and "mean_intens" in cur.columns
  has_width  = width_eps  > 0 and "width_px"   in cur.columns
  if has_intens:
    cur_int = cur["mean_intens"].to_numpy()
    nxt_int = nxt["mean_intens"].to_numpy()
  if has_width:
    cur_wid = cur["width_px"].to_numpy()
    nxt_wid = nxt["width_px"].to_numpy()

  diff = (
    cur_pts[:, np.newaxis, :]
    - nxt_pts[np.newaxis, :, :]
  )
  dist_mat = np.hypot(diff[:, :, 0], diff[:, :, 1])

  nn_cn = dist_mat.argmin(axis=1)
  d_cn  = dist_mat[np.arange(len(cur_pts)), nn_cn]
  nn_nc = dist_mat.argmin(axis=0)
  d_nc  = dist_mat[nn_nc, np.arange(len(nxt_pts))]

  for i, (dist, j) in enumerate(zip(d_cn, nn_cn)):
    if dist > max_dist:
      continue
    if nn_nc[j] != i:
      continue
    if d_nc[j] > max_dist:
      continue
    if _angle_diff(cur_ang[i], nxt_ang[j]) >= angle_eps:
      continue
    if has_intens:
      ci, ni = cur_int[i], nxt_int[j]
      if ci > 0 and ni > 0:
        mean_i = (ci + ni) / 2.0
        if abs(ci - ni) / mean_i > intens_eps:
          continue
    if has_width:
      wi, wj = cur_wid[i], nxt_wid[j]
      if wi > 0 and wj > 0:
        mean_w = (wi + wj) / 2.0
        if abs(wi - wj) / mean_w > width_eps:
          continue
    union(int(cur_ix[i]), int(nxt_ix[j]))


def link_tracks(
  df: "pd.DataFrame",
  *,
  max_dist: float   = _MAX_DIST,
  angle_eps: float  = _ANGLE_EPS,
  intens_eps: float = _INTENS_EPS,
  width_eps: float  = _WIDTH_EPS,
) -> "pd.DataFrame":
  """Add a ``track_id`` column grouping segments into 3D tracks.

    Segments in adjacent Z-slices are linked when:
    - midpoint distance < *max_dist* px  (or mm when global coords used)
    - angle difference  < *angle_eps* deg
    - relative intensity difference < *intens_eps*
      (|a−b| / mean(a,b); skipped when data absent or eps <= 0)
    - relative width difference < *width_eps*
      (|a−b| / mean(a,b); skipped when data absent or eps <= 0)

    When ``view_x_mm``, ``view_y_mm``, and ``px_scale_um`` columns are
    present (and px_scale_um > 0), midpoints are converted to global mm
    coordinates and cross-FOV linking is performed automatically.
    Otherwise linking is restricted to within each ``view_id``.

    Only mutual nearest-neighbour pairs are linked.  Segments that
    never link get a unique track_id of their own.
    """
  import pandas as pd

  df = df.copy()
  n = len(df)
  parent = list(range(n))

  def find(x: int) -> int:
    while parent[x] != x:
      parent[x] = parent[parent[x]]
      x = parent[x]
    return x

  def union(x: int, y: int) -> None:
    parent[find(x)] = find(y)

  _kw = dict(
    angle_eps=angle_eps,
    intens_eps=intens_eps,
    width_eps=width_eps,
  )

  # Global (cross-view) path: requires view offsets + px scale
  _global_cols = {"view_x_mm", "view_y_mm", "px_scale_um"}
  use_global = (
    _global_cols.issubset(df.columns)
    and float(df["px_scale_um"].max()) > 0
  )

  if use_global:
    scale_mm = float(df["px_scale_um"].median()) / 1000.0
    # global midpoints in mm
    mx = ((df["px1"] + df["px2"]) / 2.0 * scale_mm
          + df["view_x_mm"])
    my = ((df["py1"] + df["py2"]) / 2.0 * scale_mm
          + df["view_y_mm"])
    global_pts = np.column_stack([mx.to_numpy(), my.to_numpy()])
    max_dist_mm = max_dist * scale_mm

    slices = sorted(df["slice_idx"].unique())
    for s_cur, s_nxt in zip(slices[:-1], slices[1:]):
      cur = df[df["slice_idx"] == s_cur]
      nxt = df[df["slice_idx"] == s_nxt]
      if len(cur) == 0 or len(nxt) == 0:
        continue
      _match_slice_pair(
        cur, nxt, union,
        max_dist=max_dist_mm,
        cur_pts=global_pts[cur.index.to_numpy()],
        nxt_pts=global_pts[nxt.index.to_numpy()],
        **_kw,
      )
  else:
    # Fallback: intra-view linking only
    for _, vdf in df.groupby("view_id", sort=False):
      slices = sorted(vdf["slice_idx"].unique())
      for s_cur, s_nxt in zip(slices[:-1], slices[1:]):
        cur = vdf[vdf["slice_idx"] == s_cur]
        nxt = vdf[vdf["slice_idx"] == s_nxt]
        if len(cur) == 0 or len(nxt) == 0:
          continue
        _match_slice_pair(
          cur, nxt, union,
          max_dist=max_dist,
          cur_pts=_midpoints(cur),
          nxt_pts=_midpoints(nxt),
          **_kw,
        )

  # compress roots → contiguous track_ids
  roots   = [find(i) for i in range(n)]
  uniq    = {r: k for k, r in enumerate(dict.fromkeys(roots))}
  df["track_id"] = [uniq[r] for r in roots]
  return df


def best_per_track(df: "pd.DataFrame") -> "pd.DataFrame":
  """Return one representative row per track_id (highest quality).

    Quality = sqrt(length_px) * mean_intens / width_px, with each
    factor applied only when the datum is available (> 0).
    Requires ``track_id`` column (output of :func:`link_tracks`).
    """
  if "track_id" not in df.columns or len(df) == 0:
    return df

  q = df["length_px"].pow(0.5).copy()
  if "mean_intens" in df.columns:
    mask = df["mean_intens"] > 0
    q = q.where(~mask, q * df["mean_intens"])
  if "width_px" in df.columns:
    mask = df["width_px"] > 0
    q = q.where(~mask, q / df["width_px"])

  best_idx = (
    df.assign(_q=q)
    .groupby("track_id")["_q"]
    .idxmax()
  )
  return df.loc[best_idx.values].reset_index(drop=True)
