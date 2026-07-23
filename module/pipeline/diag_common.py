"""Common helpers shared by the diagnostic scripts.

Pure refactor of code previously duplicated across step5_compat, lowsp_diag,
lowsp_spread_radius, and bg_cost_spread. No logic change.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from module.pipeline import find_tracks
from module.pipeline.finder import _ZPJ_HALF

# v6 production tracking config (config/default.yaml viewer block).
TRACK_CFG = dict(
  zpj_half=4, fog_ksize=51,
  noise_amin=2, noise_amax=100, noise_cmp=50, noise_amax_upper=0,
  hough_thr=35, hough_min_line=30, hough_max_gap=40,  # was 5,
  # see config/default.yaml hough_mg comment / analysis-note.md
  # 2026-07-22
  grain_radius=15, px_scale_um=0.29,
)

# Column order for a tracks DataFrame consumed by find_vertices.
DF_COLS = [
  "view_id", "slice_idx", "px1", "py1", "px2", "py2",
  "length_px", "angle_deg", "mean_intens", "z", "view_x_mm", "view_y_mm",
]


def tracks_to_df(tracks, slice_idx: int) -> pd.DataFrame:
  """Build a find_vertices-compatible DataFrame from Track objects."""
  return pd.DataFrame([{
    "view_id": t.view_id, "slice_idx": slice_idx,
    "px1": t.px1, "py1": t.py1, "px2": t.px2, "py2": t.py2,
    "length_px": t.length_px, "angle_deg": t.angle_deg,
    "mean_intens": t.mean_intens, "z": t.z,
    "view_x_mm": t.view_x_mm, "view_y_mm": t.view_y_mm,
  } for t in tracks], columns=DF_COLS)


def projection(reader, center: int, zpj_half: int = _ZPJ_HALF):
  """find_tracks ±zpj_half mean z-projection. Returns (proj, lo, hi)."""
  lo = max(0, center - zpj_half)
  hi = min(len(reader) - 1, center + zpj_half)
  slices = [reader.read(i) for i in range(lo, hi + 1)]
  return np.mean(slices, axis=0).astype(np.uint8), lo, hi


def find_tracks_cfg(reader, slice_idx: int, view_id: str, stack=None):
  """Call find_tracks with the v6 TRACK_CFG (px_scale_um split out)."""
  tcfg = {k: v for k, v in TRACK_CFG.items() if k != "px_scale_um"}
  return find_tracks(
    reader, slice_idx, view_id=view_id,
    px_scale_um=TRACK_CFG["px_scale_um"], _stack=stack, **tcfg,
  )
