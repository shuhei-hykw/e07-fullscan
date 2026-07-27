from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
import yaml

from .track import Track
# Shared branch-neutral preprocessing. Re-exported so existing callers of
# `from module.pipeline.finder import preprocess` keep working.
from module.preprocess import fog_remove, preprocess

# Single source of truth for production parameters: config/default.yaml's
# `viewer` block, the same one analyze_cli.py and server/app.py read.
# These used to be hardcoded here and drifted out of sync with the yaml
# TWICE (hough_mg 4 vs 5, grain_radius 10 vs 15), each time silently
# degrading detection until someone measured it -- hough_mg=4 was found
# to miss 56% of confirmed real track pixels. Reading the yaml removes
# that whole class of bug rather than documenting around it.
# See analysis-note.md 2026-07-22/23.
_CFG_PATH = Path(__file__).parents[2] / "config" / "default.yaml"
_FALLBACK = {
  "zpj_half": 4, "fog_ksize": 51,
  "noise_amin": 2, "noise_amax": 100, "noise_cmp": 50,
  "noise_amax_upper": 0,  # 0 = disabled; >0 removes blobs larger than this
  "hough_thr": 35, "hough_ml": 30, "hough_mg": 40,
  "grain_radius": 15,
}


def _load_viewer_cfg() -> dict:
  """viewer block from config/default.yaml, falling back to _FALLBACK
  when the file is missing or unreadable (e.g. the package used
  standalone). Fallback values mirror the yaml as of 2026-07-27."""
  try:
    if _CFG_PATH.exists():
      raw = yaml.safe_load(_CFG_PATH.read_text()) or {}
      cfg = dict(_FALLBACK)
      cfg.update(raw.get("viewer", {}) or {})
      return cfg
  except Exception:
    pass
  return dict(_FALLBACK)


_CFG = _load_viewer_cfg()
_ZPJ_HALF    = int(_CFG["zpj_half"])
_FOG_KSIZE   = int(_CFG["fog_ksize"])
_NOISE_AMIN  = int(_CFG["noise_amin"])
_NOISE_AMAX  = int(_CFG["noise_amax"])
_NOISE_CMP   = int(_CFG["noise_cmp"])
_NOISE_AMAX_UPPER = int(_CFG["noise_amax_upper"])
_HOUGH_THR   = int(_CFG["hough_thr"])
_HOUGH_ML    = int(_CFG["hough_ml"])
_HOUGH_MG    = int(_CFG["hough_mg"])
_GRAIN_RADIUS = float(_CFG["grain_radius"])
_FOOTPRINT_MAX_SEARCH_PX = 15  # max perpendicular search for
                                # _footprint_width


def _measure_tracks(
  fog_img: np.ndarray,
  binary: np.ndarray,
  lines: np.ndarray,
  grain_radius: float,
) -> list[tuple[int, float, float]]:
  """Return (n_grains, width_px, mean_intens) for each track segment.

  grain_radius: distance threshold (px) to associate a grain blob
  with a segment.
  """
  contours, _ = cv2.findContours(
    binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
  )
  cx_list: list[float] = []
  cy_list: list[float] = []
  for cnt in contours:
    M = cv2.moments(cnt)
    if M["m00"] > 0:
      cx_list.append(M["m10"] / M["m00"])
      cy_list.append(M["m01"] / M["m00"])

  h, w = fog_img.shape[:2]
  results: list[tuple[int, float, float]] = []

  C = np.column_stack([cx_list, cy_list]) if cx_list else None

  for x1, y1, x2, y2 in lines:
    dx = float(x2 - x1)
    dy = float(y2 - y1)
    seg_len2 = dx * dx + dy * dy
    seg_len = math.sqrt(seg_len2) if seg_len2 > 0 else 0.0

    # mean intensity: sample fog-removed image along the segment
    n_pts = max(int(seg_len), 1)
    xs = np.round(np.linspace(x1, x2, n_pts + 1)).astype(int)
    ys = np.round(np.linspace(y1, y2, n_pts + 1)).astype(int)
    valid = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    mean_intens = (
      float(fog_img[ys[valid], xs[valid]].mean())
      if valid.any() else 0.0
    )

    if seg_len == 0 or C is None:
      results.append((0, 0.0, mean_intens))
      continue

    # distance from each grain centroid to the nearest point on segment
    t = np.clip(
      ((C[:, 0] - x1) * dx + (C[:, 1] - y1) * dy) / seg_len2,
      0.0, 1.0,
    )
    seg_dists = np.hypot(
      C[:, 0] - (x1 + t * dx), C[:, 1] - (y1 + t * dy)
    )
    near = seg_dists < grain_radius
    n_grains = int(near.sum())

    if n_grains > 1:
      # perpendicular distance = |cross product| / seg_len
      perp = np.abs(
        (C[near, 0] - x1) * dy - (C[near, 1] - y1) * dx
      ) / seg_len
      width_px = float(perp.std())
    elif n_grains == 1:
      width_px = 0.0
    else:
      width_px = 0.0

    results.append((n_grains, width_px, mean_intens))

  return results


def _footprint_width(t, binary: np.ndarray) -> float:
  """Median cross-sectional thickness of the RAW (non-dilated) binary
  mask, sampled perpendicular to the segment at each ~1px step along
  it. Unlike the width_px this module returns above (a grain-centroid
  scatter statistic, unstable at low n_grains and shown to have ~no
  track/junk separation -- see analysis-note.md 2026-07-21), this
  measures the actual foreground footprint: a stable, physically
  meaningful width (px, convertible to um) that does separate
  track/junk. Shared by track_classifier.py (as a classifier feature)
  and cluster.py (as a fragment-merge quality score), both of which
  import it from here to avoid a module.pipeline <-> track_classifier
  circular import."""
  h, w = binary.shape
  seg_len = max(t.length_px, 1.0)
  ux = (t.px2 - t.px1) / seg_len
  uy = (t.py2 - t.py1) / seg_len
  pxu, pyu = -uy, ux
  n = max(int(t.length_px), 2)
  xs = np.linspace(t.px1, t.px2, n)
  ys = np.linspace(t.py1, t.py2, n)
  cx = np.clip(np.round(xs).astype(int), 0, w - 1)
  cy = np.clip(np.round(ys).astype(int), 0, h - 1)
  center_fg = binary[cy, cx] > 0
  run = np.zeros(n, dtype=np.int32)
  for sign in (1, -1):
    active = center_fg.copy()
    for k in range(1, _FOOTPRINT_MAX_SEARCH_PX):
      px = np.clip(np.round(xs + sign * k * pxu).astype(int), 0, w - 1)
      py = np.clip(np.round(ys + sign * k * pyu).astype(int), 0, h - 1)
      active &= binary[py, px] > 0
      run += active.astype(np.int32)
  widths = np.where(center_fg, run + 1, 0)
  fg_widths = widths[widths > 0]
  return float(np.median(fg_widths)) if fg_widths.size else 0.0


def _pixel_to_stage(
  affine: list[float], px: float, py: float
) -> tuple[float, float]:
  # affine_p2s layout: [a00, a01, a10, a11, tx, ty]
  # stage_x = a00*px + a01*py + tx
  # stage_y = a10*px + a11*py + ty
  a00, a01, a10, a11, tx, ty = affine
  return a00 * px + a01 * py + tx, a10 * px + a11 * py + ty


def find_tracks(
  reader,
  idx: int,
  *,
  view_id: str    = "",
  zpj_half: int   = _ZPJ_HALF,
  fog_ksize: int  = _FOG_KSIZE,
  noise_amin: int = _NOISE_AMIN,
  noise_amax: int = _NOISE_AMAX,
  noise_cmp: int  = _NOISE_CMP,
  noise_amax_upper: int = _NOISE_AMAX_UPPER,
  hough_thr: int  = _HOUGH_THR,
  hough_min_line: int  = _HOUGH_ML,
  hough_max_gap: int   = _HOUGH_MG,
  grain_radius: float  = _GRAIN_RADIUS,
  px_scale_um: float   = 0.0,
  _stack: "np.ndarray | None" = None,
) -> list[Track]:
  """Detect tracks in one Z-slice and return them in stage coordinates.

  Parameters
  ----------
  reader:
    SpngReader for the view.
  idx:
    Target slice index within the reader.
  view_id:
    Identifier stored in each Track (typically the JSON path).
  grain_radius:
    Search radius (px) for associating grain blobs with a segment.
  _stack:
    Optional pre-loaded (N, H, W) uint8 array of all slices.
    When provided, no file I/O is performed for z-projection.
  """
  lo = max(0, idx - zpj_half)
  hi = min(len(reader) - 1, idx + zpj_half)
  if _stack is not None:
    img = _stack[lo:hi + 1].mean(axis=0).astype(np.uint8)
  else:
    slices = [reader.read(i) for i in range(lo, hi + 1)]
    img = np.mean(slices, axis=0).astype(np.uint8)

  # fog-removed image for intensity measurement (same impl as preprocess)
  fog_img = fog_remove(img, fog_ksize)

  binary = preprocess(
    img,
    fog_ksize=fog_ksize,
    noise_amin=noise_amin,
    noise_amax=noise_amax,
    noise_cmp=noise_cmp,
    noise_amax_upper=noise_amax_upper,
  )

  lines = cv2.HoughLinesP(
    binary, 1, np.pi / 180,
    threshold=hough_thr,
    minLineLength=hough_min_line,
    maxLineGap=hough_max_gap,
  )
  if lines is None:
    return []

  # OpenCV 4 returns (N, 1, 4); OpenCV 5 returns (N, 4)
  line_arr = lines.reshape(-1, 4)
  measurements = _measure_tracks(fog_img, binary, line_arr, grain_radius)

  entry = reader.entries[idx]
  affine = reader.affine_p2s
  tracks = []
  for (x1p, y1p, x2p, y2p), (n_g, wid, intens) in zip(
    line_arr, measurements
  ):
    sx1, sy1 = _pixel_to_stage(affine, float(x1p), float(y1p))
    sx2, sy2 = _pixel_to_stage(affine, float(x2p), float(y2p))
    length = float(np.hypot(x2p - x1p, y2p - y1p))
    angle = float(
      np.degrees(np.arctan2(y2p - y1p, x2p - x1p)) % 180
    )
    tracks.append(Track(
      x1=sx1, y1=sy1,
      x2=sx2, y2=sy2,
      z=entry.z,
      px1=int(x1p), py1=int(y1p),
      px2=int(x2p), py2=int(y2p),
      length_px=length,
      angle_deg=angle,
      view_id=view_id,
      n_grains=n_g,
      width_px=wid,
      mean_intens=intens,
      px_scale_um=px_scale_um,
      view_x_mm=entry.x,
      view_y_mm=entry.y,
    ))
  return tracks
