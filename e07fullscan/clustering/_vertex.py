from __future__ import annotations

import numpy as np
import pandas as pd

_MIN_TRACKS       = 3
_MAX_IMPACT       = 30.0   # px — perpendicular distance to vertex line
_MAX_EP           = 150.0  # px — absolute nearest-endpoint limit
_MAX_EP_FRAC      = 0.5    # relative limit: ep < frac * track_length
_MIN_INTENS       = 10.0   # lower cut for efficiency (was 12)
_EPS_PX           = 25.0   # clustering radius (px) = 7.3 μm at 0.29 μm/px
_MIN_LEN_PX       = 50.0   # px = 14.5 μm — catches alpha (25 μm = 86 px)
_BEAM_ANGLE_CUT   = 0.0    # deg — exclude |angle| < cut and |180-angle| < cut
_MIN_ANGLE_SPREAD = 0.0    # deg — 0 = disabled; reject if spread < threshold


def _angle_spread_deg(angles: np.ndarray) -> float:
  """Circular spread of line directions in [0, 180).

  Uses the doubled-angle trick to handle the 0/180 wraparound:
  maps each direction θ → exp(2iθ), then measures how spread the
  unit vectors are.  Returns half-angle spread in [0, 90]:
    0  = all lines parallel (heavy-track fake signature)
    45 = lines uniformly distributed (ideal star vertex)
  """
  phi = np.deg2rad(2.0 * angles)
  R = float(np.abs(np.mean(np.exp(1j * phi))))
  return float(np.degrees(np.arccos(np.clip(R, -1.0, 1.0))) / 2.0)


def _vertices_in_group(
  rows: pd.DataFrame,
  max_impact: float,
  max_ep: float,
  max_ep_frac: float,
  eps_px: float,
  min_tracks: int,
  min_angle_spread: float,
) -> list[dict]:
  n = len(rows)
  if n < 2:
    return []

  x1 = rows['px1'].values.astype(np.float32)
  y1 = rows['py1'].values.astype(np.float32)
  x2 = rows['px2'].values.astype(np.float32)
  y2 = rows['py2'].values.astype(np.float32)
  dx = x2 - x1
  dy = y2 - y1

  # vectorised: all pairs (i, j) with i < j
  ii, jj = np.triu_indices(n, k=1)
  dx1, dy1 = dx[ii], dy[ii]
  dx2, dy2 = dx[jj], dy[jj]

  denom = dx1 * dy2 - dy1 * dx2
  parallel = np.abs(denom) < 1e-6
  denom = np.where(parallel, 1.0, denom)

  t = ((x1[jj] - x1[ii]) * dy2 - (y1[jj] - y1[ii]) * dx2) / denom

  vx = x1[ii] + t * dx1
  vy = y1[ii] + t * dy1

  # bounds filter
  in_bounds = (~parallel
         & (vx >= -512) & (vx <= 2560)
         & (vy >= -512) & (vy <= 2560))

  vx, vy = vx[in_bounds], vy[in_bounds]
  pi, pj = ii[in_bounds], jj[in_bounds]
  dx1b, dy1b = dx[pi], dy[pi]
  dx2b, dy2b = dx[pj], dy[pj]
  Lb = np.hypot(dx1b, dy1b)
  Lc = np.hypot(dx2b, dy2b)

  # perpendicular distances
  imp_i = np.where(
    Lb > 1e-8,
    np.abs((vx - x1[pi]) * dy1b - (vy - y1[pi]) * dx1b) / Lb,
    np.hypot(vx - x1[pi], vy - y1[pi]),
  )
  imp_j = np.where(
    Lc > 1e-8,
    np.abs((vx - x1[pj]) * dy2b - (vy - y1[pj]) * dx2b) / Lc,
    np.hypot(vx - x1[pj], vy - y1[pj]),
  )
  # endpoint proximity: nearest endpoint must be within both an absolute
  # limit (max_ep) AND a fraction of the track length (max_ep_frac).
  # The fractional cut rejects short crossing tracks whose midpoint
  # is near the intersection — a 50 px crossing has nearest_ep ~25 px,
  # which looks close in absolute terms but is 0.5 × length.
  ep_i = np.minimum(
    np.hypot(vx - x1[pi], vy - y1[pi]),
    np.hypot(vx - x2[pi], vy - y2[pi]),
  )
  ep_j = np.minimum(
    np.hypot(vx - x1[pj], vy - y1[pj]),
    np.hypot(vx - x2[pj], vy - y2[pj]),
  )
  ep_lim_i = np.minimum(max_ep, max_ep_frac * Lb)
  ep_lim_j = np.minimum(max_ep, max_ep_frac * Lc)
  ok = ((imp_i < max_impact) & (imp_j < max_impact)
      & (ep_i < ep_lim_i)  & (ep_j < ep_lim_j))
  if not ok.any():
    return []

  vx, vy = vx[ok], vy[ok]
  pi, pj = pi[ok], pj[ok]

  # grid-based clustering: bin intersections into eps_px cells
  ox = vx.min(); oy = vy.min()
  gx = ((vx - ox) / eps_px).astype(np.int32)
  gy = ((vy - oy) / eps_px).astype(np.int32)
  keys = gx * 100003 + gy  # hash-like key
  order = np.argsort(keys)
  vx, vy, pi, pj, keys = (
    vx[order], vy[order], pi[order], pj[order], keys[order]
  )
  # assign label = index of first point in each key group
  _, first_idx = np.unique(keys, return_index=True)
  labels = np.empty(len(keys), dtype=np.int32)
  for fi, f in enumerate(first_idx):
    end = first_idx[fi + 1] if fi + 1 < len(first_idx) else len(keys)
    labels[f:end] = fi

  has_angle = 'angle_deg' in rows.columns

  results: list[dict] = []
  for lbl in range(len(first_idx)):
    mask = labels == lbl
    cluster_vx = vx[mask].mean()
    cluster_vy = vy[mask].mean()
    track_idx = set(pi[mask].tolist()) | set(pj[mask].tolist())
    if len(track_idx) < min_tracks:
      continue
    tr = rows.iloc[sorted(track_idx)]

    spread = (
      _angle_spread_deg(tr['angle_deg'].values)
      if has_angle else float('nan')
    )
    if min_angle_spread > 0.0 and has_angle:
      if spread < min_angle_spread:
        continue

    results.append({
      'vx_px':        float(cluster_vx),
      'vy_px':        float(cluster_vy),
      'n_tracks':     len(track_idx),
      'mean_intens':  float(tr['mean_intens'].mean()),
      'angle_spread': spread,
      'z':            float(rows['z'].mean()),
      'view_id':      rows['view_id'].iloc[0],
      'view_x_mm':    float(rows['view_x_mm'].iloc[0]),
      'view_y_mm':    float(rows['view_y_mm'].iloc[0]),
    })
  return results


def find_vertices(
  df: pd.DataFrame,
  min_tracks: int          = _MIN_TRACKS,
  max_impact: float        = _MAX_IMPACT,
  max_ep: float            = _MAX_EP,
  max_ep_frac: float       = _MAX_EP_FRAC,
  min_intens: float        = _MIN_INTENS,
  eps_px: float            = _EPS_PX,
  min_len_px: float        = _MIN_LEN_PX,
  beam_angle_cut: float    = _BEAM_ANGLE_CUT,
  min_angle_spread: float  = _MIN_ANGLE_SPREAD,
) -> pd.DataFrame:
  """Find 2D vertex candidates per (view_id, slice_idx).

  Intersects all pairs of quality-selected track lines, clusters
  the intersection points, and returns clusters with >= min_tracks
  contributing tracks.

  Endpoint check: nearest endpoint must satisfy BOTH
    ep < max_ep  (absolute px limit)
    ep < max_ep_frac * track_length  (relative limit)
  The relative limit rejects short crossing tracks whose midpoint
  happens to be near the intersection.

  beam_angle_cut > 0 removes tracks with angle_deg < cut or
  angle_deg > 180 - cut (nearly beam-parallel tracks).

  min_angle_spread > 0 rejects clusters where the circular spread of
  contributing track directions is below the threshold (in degrees).
  Uses doubled-angle trick to handle 0/180 wraparound; spread=0 means
  all tracks parallel (heavy-particle fake), spread=45 means uniform.
  Recommended: 20-30 deg.  0 = disabled (default).

  Returns DataFrame with columns:
    view_id, slice_idx, vx_px, vy_px, z, n_tracks,
    mean_intens, angle_spread, view_x_mm, view_y_mm
  """
  sel = df[
    (df['mean_intens'] >= min_intens) &
    (df['length_px']   >= min_len_px)
  ]
  if beam_angle_cut > 0.0 and 'angle_deg' in sel.columns:
    sel = sel[
      (sel['angle_deg'] > beam_angle_cut) &
      (sel['angle_deg'] < 180.0 - beam_angle_cut)
    ]

  records: list[dict] = []
  for (view_id, slice_idx), grp in sel.groupby(
    ['view_id', 'slice_idx'], sort=False
  ):
    for v in _vertices_in_group(
      grp.reset_index(drop=True),
      max_impact, max_ep, max_ep_frac, eps_px,
      min_tracks, min_angle_spread,
    ):
      v['slice_idx'] = int(slice_idx)
      records.append(v)

  if not records:
    return pd.DataFrame(columns=[
      'view_id', 'slice_idx', 'vx_px', 'vy_px', 'z',
      'n_tracks', 'mean_intens', 'angle_spread',
      'view_x_mm', 'view_y_mm',
    ])
  return pd.DataFrame(records)


_EPS_XY_MERGE  = 50.0  # px — XY proximity to merge across slices
_MIN_SLICES    = 1     # minimum slice count to retain merged vertex


def merge_vertex_slices(
  df: pd.DataFrame,
  eps_xy: float   = _EPS_XY_MERGE,
  min_slices: int = _MIN_SLICES,
) -> pd.DataFrame:
  """Merge vertex candidates across slice_idx within the same view.

  Vertices in the same view within eps_xy pixels are assumed to be
  the same physical vertex seen in overlapping z-projections.
  Outputs one row per merged vertex with:
    vx_px, vy_px  — n_tracks-weighted mean position
    n_tracks_max  — max n_tracks across contributing slices
    n_slices      — number of distinct slice_idx that voted for it
    z_mean        — weighted mean z
    z_min, z_max  — z depth range of contributing slices
  """
  records: list[dict] = []

  for view_id, grp in df.groupby('view_id', sort=False):
    vx  = grp['vx_px'].values.astype(np.float32)
    vy  = grp['vy_px'].values.astype(np.float32)
    nt  = grp['n_tracks'].values.astype(np.float32)
    sl  = grp['slice_idx'].values
    zv  = grp['z'].values.astype(np.float32)
    mi  = grp['mean_intens'].values.astype(np.float32)
    n   = len(grp)
    assigned = np.zeros(n, dtype=bool)

    # process in descending n_tracks order
    order = np.argsort(-nt)

    for oi in order:
      if assigned[oi]:
        continue
      dists = np.hypot(vx - vx[oi], vy - vy[oi])
      near  = dists < eps_xy
      assigned[near] = True

      w   = nt[near]
      ws  = w.sum()
      vxm = float((vx[near] * w).sum() / ws)
      vym = float((vy[near] * w).sum() / ws)
      zm  = float((zv[near] * w).sum() / ws)
      n_sl = int(np.unique(sl[near]).size)
      if n_sl < min_slices:
        continue
      records.append({
        'view_id':      view_id,
        'vx_px':        vxm,
        'vy_px':        vym,
        'n_tracks_max': int(nt[near].max()),
        'n_slices':     n_sl,
        'z_mean':       zm,
        'z_min':        float(zv[near].min()),
        'z_max':        float(zv[near].max()),
        'mean_intens':  float(mi[near].mean()),
        'view_x_mm':    float(grp['view_x_mm'].iloc[0]),
        'view_y_mm':    float(grp['view_y_mm'].iloc[0]),
      })

  if not records:
    return pd.DataFrame()
  return pd.DataFrame(records)
