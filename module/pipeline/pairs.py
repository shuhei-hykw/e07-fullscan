"""Legacy ΛΛ-pair topology vertex finder.

Superseded on 2026-05-14 when the analysis switched from requiring a
primary+secondary vertex pair to detecting individual reaction vertices
directly (see ANALYSIS.md). Kept for provenance and comparison: it produced
the historical ΛΛ pair catalogs and the KISO cross-view result. Not part of
the current individual-vertex pipeline.

Re-exported from clustering/__init__.py as `find_vertex_pairs`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ΛΛ topology constants (0.29 μm/px scanner scale)
_PX_SCALE_UM = 0.29   # μm/px confirmed: FOV=594 μm / 2048 px
_D_MIN_PX    = 310.0  # 90 μm / 0.29 μm/px
_D_MAX_PX    = 1724.0 # 500 μm / 0.29 μm/px
_MIN_N_SEC   = 3      # minimum n_tracks_max for secondary vertex
_MAX_DZ_MM   = 0.010  # max Z separation in mm (10 μm ≈ 3 z-slices)
_MIN_SL_SEC  = 2      # min n_slices for secondary vertex


def find_vertex_pairs(
  df: pd.DataFrame,
  d_min_px:       float = _D_MIN_PX,
  d_max_px:       float = _D_MAX_PX,
  min_n_primary:  int   = 5,
  min_n_secondary: int  = _MIN_N_SEC,
  min_sl_secondary: int = _MIN_SL_SEC,
  max_dz_mm:      float = _MAX_DZ_MM,
) -> pd.DataFrame:
  """Find ΛΛ-topology vertex pairs: one primary + one secondary vertex.

  Both vertices must be in the same view. Primary vertex has
  n_tracks_max >= min_n_primary; secondary vertex has n_tracks_max >=
  min_n_secondary AND n_slices >= min_sl_secondary. Pair XY separation
  is [d_min_px, d_max_px]. Z separation must be < max_dz_mm (mm units,
  same as z_mean column: z_step ≈ 0.003 mm = 3 μm).

  Returns a DataFrame with one row per candidate pair:
    view_id, view_x_mm, view_y_mm,
    p_vx, p_vy, p_ntracks, p_nslices, p_z,    (primary)
    s_vx, s_vy, s_ntracks, s_nslices, s_z,    (secondary)
    dist_px, dist_um, dz_um
  """
  has_nslices = 'n_slices' in df.columns
  has_spread  = 'angle_spread_best' in df.columns
  records: list[dict] = []
  PX_SCALE = _PX_SCALE_UM  # 0.29 μm/px

  for view_id, grp in df.groupby('view_id', sort=False):
    grp = grp.reset_index(drop=True)
    vx = grp['vx_px'].values.astype(np.float32)
    vy = grp['vy_px'].values.astype(np.float32)
    nt = grp['n_tracks_max'].values
    zv = grp['z_mean'].values.astype(np.float32)
    nsl = grp['n_slices'].values if has_nslices else np.ones(len(grp))
    sp  = (grp['angle_spread_best'].values.astype(np.float32)
           if has_spread else None)

    primary = np.where(nt >= min_n_primary)[0]
    secondary = np.where(
      (nt >= min_n_secondary) & (nsl >= min_sl_secondary)
    )[0]
    if len(primary) == 0 or len(secondary) == 0:
      continue

    for pi in primary:
      dists = np.hypot(vx[secondary] - vx[pi], vy[secondary] - vy[pi])
      dz    = np.abs(zv[secondary] - zv[pi])
      for k, si in enumerate(secondary):
        if si == pi:
          continue
        d = float(dists[k])
        if d < d_min_px or d > d_max_px:
          continue
        if float(dz[k]) > max_dz_mm:
          continue
        rec = {
          'view_id':    view_id,
          'view_x_mm':  float(grp['view_x_mm'].iloc[0]),
          'view_y_mm':  float(grp['view_y_mm'].iloc[0]),
          'p_vx':       float(vx[pi]),
          'p_vy':       float(vy[pi]),
          'p_ntracks':  int(nt[pi]),
          'p_nslices':  int(nsl[pi]),
          'p_z':        float(zv[pi]),
          's_vx':       float(vx[si]),
          's_vy':       float(vy[si]),
          's_ntracks':  int(nt[si]),
          's_nslices':  int(nsl[si]),
          's_z':        float(zv[si]),
          'dist_px':    d,
          'dist_um':    d * PX_SCALE,
          'dz_mm':      float(dz[k]),
        }
        if has_spread and sp is not None:
          rec['p_angle_spread'] = (
            float(sp[pi]) if not np.isnan(sp[pi]) else 0.0)
          rec['s_angle_spread'] = (
            float(sp[si]) if not np.isnan(sp[si]) else 0.0)
        records.append(rec)

  if not records:
    return pd.DataFrame()
  return pd.DataFrame(records)
