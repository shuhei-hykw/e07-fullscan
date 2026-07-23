"""Export a tile as a 3-D hit-pixel list for the MATLAB graph detector.

Bridges the Python full-scan pipeline to the graph-theory event detector in
``e07/matlab`` (``detect_tracks.m`` + helpers). That detector's stage-1 input
is a 3-D hit pixel list ``pl = {x, y, z, n, sheet, id}`` (x, y in pixels,
z = slice index); its downstream stages only use ``dspl = mabiki(pl, 3)``.

Unlike the Hough pipeline, which z-projects the stack into one 2-D image, the
graph detector needs the full z extent. So each slice is binarized
independently (fog removal -> Otsu -> noise removal, reused from
``module.preprocess``).

Default mode (``grid``): connected components for grouping (a basic
connectivity primitive, not shape/line clustering), then one
intensity-weighted 3-D hit per occupied ``_GRID_CELL_PX`` x
``_GRID_CELL_PX`` cell *within* each component. Two earlier, simpler
schemes were tried and dropped:

- One hit per connected component (whole-blob centroid): tractable
  (~2.5h/tile) but a long, continuously-connected track is a *single*
  component, so its whole length -- and all its line/vertex information
  -- collapsed into one hit.
- A plain global grid (position only, ignoring connectivity): fixes the
  long-track collapse, but a cell can average pixels from two distinct,
  disconnected tracks that happen to pass close together (most visible
  right at a real vertex, where several tracks converge) into one
  spurious blended hit -- exactly where fidelity matters most.

Grouping by connected component first, then re-sampling on a fixed grid
*within* each component, gets both properties at roughly the plain grid's
cost: a cell's hit is always drawn from one physical grain/track, and no
single component -- however long -- collapses to one point. A raw-pixel
mode (``pixel``, one hit per binary pixel) is kept for comparison but is
so dense it makes ``detectlseg_smallregion`` take an estimated 600+ days
on real data (see analysis-note.md, 2026-07-11 to 07-12 entries).

Large components are additionally thinned to a 1-px skeleton
(centreline) before cell sampling: real track width after binarisation
(~13-16 px locally) is 4-8x wider than ``detectlseg_smallregion``'s own
straightness tolerance (TH=1.5-2 px), which otherwise fragments tracks
into many short segments -- confirmed to even crash a downstream MATLAB
merge step (``integrate_smallregions``) on real KISO data (analysis-note.
md, 2026-07-12). See ``weighted_grid_hits`` for the skeleton step.

Coordinates are 1-based (x = col + 1, y = row + 1, z = slice + 1) to match the
MATLAB convention of a (1, 1, 1) origin and its ``x > lb`` small-region split.

The block-3 down-sampling (``mabiki``) is intentionally left to MATLAB; this
writer emits ``pl`` only (not pre-downsampled).

  python -m module.matlab_export tile.json -o tile_pl.mat
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from scipy.io import savemat
from skimage.morphology import skeletonize

from module import track_classifier
from module.preprocess import (
  _FOG_KSIZE,
  _NOISE_AMAX,
  _NOISE_AMAX_UPPER,
  _NOISE_AMIN,
  _NOISE_CMP,
  fog_remove,
  otsu_binarize,
  remove_noise,
)
from module.reader import load_spng

# MATLAB column layout for the hit pixel list (see detect_tracks.m).
_PL_VARNAMES = ["x", "y", "z", "n", "sheet", "id"]
# No track segmentation exists for real data, so sheet/id are placeholders.
_SHEET_PLACEHOLDER = 0
_ID_PLACEHOLDER = 0
# 1-based origin to match MATLAB's (1, 1, 1) start.
_ORIGIN_OFFSET = 1
_MODE_PIXEL = "pixel"
_MODE_GRID = "grid"
_DEFAULT_MODE = _MODE_GRID
# Spatial bin size for grid mode (px). Chosen from a density/runtime sweep
# on KISO (analysis-note.md, 2026-07-11 entry): keeps detectlseg_smallregion
# near its proven ~2.5h/tile (connected-component mode) run time while
# guaranteeing >=1 sample per ~_GRID_CELL_PX along any track, however long.
_GRID_CELL_PX = 30
# Noise-filter parameters (see remove_unaligned_noise). Chosen from a
# sweep on KISO (analysis-note.md, 2026-07-12): removes ~19% of the point
# budget while a vertex-region visual check confirmed real track-aligned
# blobs survive.
_HOUGH_THR = 8
_HOUGH_MIN_LINE = 10
_HOUGH_MAX_GAP = 3
_ALIGN_TOL_PX = 3.0
_NOISE_AREA_FLOOR = 30.0

# remove_unaligned_noise_v2: segment-level filter using module/server/
# labeling.py's manual true/false labels (results/manual_labels/,
# 512 decisions across 4 tiles as of 2026-07-18), rather than the
# hard-coded align_tol/area_floor heuristic above. Hough params here
# intentionally match labeling.py's own defaults (not this module's
# _HOUGH_MAX_GAP=3 above) -- the classifier and the threshold values
# below were both fit against segments detected at max_gap=20, so
# scoring segments detected at a different max_gap would feed it
# out-of-distribution inputs.
_NOISE_V2_HOUGH_THR = 8
_NOISE_V2_HOUGH_MIN_LINE = 10
_NOISE_V2_HOUGH_MAX_GAP = 20
# Non-ML fallback thresholds: grid search over cov_frac/max_gap_px on
# all 512 labelled decisions, best F1 (analysis-note.md, 2026-07-18).
# Precision 58.7% / recall 89.7% on the labelled set alone -- clearly
# worse than the trained classifier (leave-one-tile-out precision
# 73-93%, recall 53-96%) but needs no model file, just these two
# numbers.
_NOISE_V2_COV_FRAC_THR = 0.725
_NOISE_V2_MAX_GAP_THR_PX = 19
_DEFAULT_LABELS_DIR = Path(__file__).parents[1] / "results" / "manual_labels"


def _binarize_slice(
  reader,
  z: int,
  fog_ksize: int,
  noise_amin: int,
  noise_amax: int,
  noise_cmp: int,
  noise_amax_upper: int,
) -> tuple[np.ndarray, np.ndarray]:
  """Return (fog-removed image, binary mask) for one slice."""
  img = reader.read(z)
  fog = fog_remove(img, fog_ksize)
  _, binary = otsu_binarize(fog)
  binary = remove_noise(
    binary, noise_amin, noise_amax, noise_cmp, noise_amax_upper
  )
  return fog, binary


def export_hits(
  json_path: Path | str,
  fog_ksize: int = _FOG_KSIZE,
  noise_amin: int = _NOISE_AMIN,
  noise_amax: int = _NOISE_AMAX,
  noise_cmp: int = _NOISE_CMP,
  noise_amax_upper: int = _NOISE_AMAX_UPPER,
) -> np.ndarray:
  """Build the MATLAB hit pixel list ``pl`` (N x 6) for one tile.

  Each slice is binarized independently; every foreground pixel becomes one
  3-D hit, with intensity ``n`` taken from the fog-removed image. This is
  the raw-pixel mode: dense (one hit per binary pixel), ~95x denser than
  ``export_hits_grid``. Kept for comparison; not the default CLI mode.
  """
  reader = load_spng(json_path)
  cols = []
  for z in range(len(reader)):
    fog, binary = _binarize_slice(
      reader, z, fog_ksize, noise_amin, noise_amax, noise_cmp,
      noise_amax_upper,
    )
    ys, xs = np.nonzero(binary)
    if xs.size == 0:
      continue
    n = fog[ys, xs].astype(np.float64)
    block = np.empty((xs.size, len(_PL_VARNAMES)), dtype=np.float64)
    block[:, 0] = xs + _ORIGIN_OFFSET            # x = col
    block[:, 1] = ys + _ORIGIN_OFFSET            # y = row
    block[:, 2] = z + _ORIGIN_OFFSET             # z = slice index
    block[:, 3] = n                              # intensity proxy
    block[:, 4] = _SHEET_PLACEHOLDER
    block[:, 5] = _ID_PLACEHOLDER
    cols.append(block)
  if not cols:
    return np.empty((0, len(_PL_VARNAMES)), dtype=np.float64)
  return np.concatenate(cols, axis=0)


def _weighted_centroid(
  weighted_block: np.ndarray, mask_block: np.ndarray, ox: int, oy: int,
) -> tuple[float, float]:
  """Intensity-weighted centroid of one block; falls back to the
  geometric mean if the block's intensity happens to sum to zero
  (shouldn't normally happen post fog+Otsu)."""
  M = cv2.moments(weighted_block, binaryImage=False)
  if M["m00"] > 0:
    return M["m10"] / M["m00"] + ox, M["m01"] / M["m00"] + oy
  ys, xs = np.nonzero(mask_block)
  return float(xs.mean()) + ox, float(ys.mean()) + oy


def _line_alignment_dist(pts: np.ndarray, lines: np.ndarray) -> np.ndarray:
  """Min perpendicular distance from each point to any Hough line segment
  (each segment extended 30% past its own endpoints, to bridge small
  binarisation gaps along a real track)."""
  if len(lines) == 0 or len(pts) == 0:
    return np.full(len(pts), np.inf)
  x1, y1, x2, y2 = lines[:, 0], lines[:, 1], lines[:, 2], lines[:, 3]
  dx, dy = x2 - x1, y2 - y1
  seg_len2 = np.maximum(dx * dx + dy * dy, 1e-9)
  px, py = pts[:, 0:1], pts[:, 1:2]
  best = np.full(len(pts), np.inf)
  batch = 500  # bound the (n_pts x n_lines) intermediate array
  for i in range(0, len(lines), batch):
    bx1, by1 = x1[i:i + batch], y1[i:i + batch]
    bdx, bdy = dx[i:i + batch], dy[i:i + batch]
    bl2 = seg_len2[i:i + batch]
    t = np.clip(((px - bx1) * bdx + (py - by1) * bdy) / bl2, -0.3, 1.3)
    cx, cy = bx1 + t * bdx, by1 + t * bdy
    d = np.hypot(px - cx, py - cy)
    best = np.minimum(best, d.min(axis=1))
  return best


def remove_unaligned_noise(
  binary: np.ndarray,
  cell: int = _GRID_CELL_PX,
  hough_thr: int = _HOUGH_THR,
  hough_min_line: int = _HOUGH_MIN_LINE,
  hough_max_gap: int = _HOUGH_MAX_GAP,
  align_tol: float = _ALIGN_TOL_PX,
  area_floor: float = _NOISE_AREA_FLOOR,
) -> np.ndarray:
  """Drop small, isolated connected components that don't lie near any
  per-slice Hough-detected line -- likely noise, not real grain-cluster
  fragments of a track.

  Two other classical discriminators were tried and failed (analysis-note.
  md, 2026-07-12): elongation (no correlation with area, r ~= -0.09) and
  isolation distance to the nearest other structure (median 21px
  regardless of real/noise -- the image is simply dense everywhere).
  Hough-line alignment succeeds: components >= align_tol px from every
  detected line have median area ~20px vs ~114px for aligned ones.

  Only small (<= cell px extent) components are considered -- these are
  the ones NOT already skeletonized/decimated by weighted_grid_hits, and
  the ones responsible for ~66% of KISO's point budget. A component is
  removed only if BOTH unaligned AND area < area_floor: alignment alone
  would also drop some substantial (up to ~170px area) blobs sitting
  directly on real track lines near the known KISO vertex (visually
  confirmed) -- the area floor keeps this conservative, favouring recall
  (the project's efficiency-first policy) over a bigger point-count cut.
  """
  n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
    binary, connectivity=8
  )
  small_idx = np.array([
    lbl for lbl in range(1, n_labels)
    if stats[lbl][4] > 0 and max(stats[lbl][2], stats[lbl][3]) <= cell
  ])
  if small_idx.size == 0:
    return binary

  lines = cv2.HoughLinesP(
    binary, 1, np.pi / 180, threshold=hough_thr,
    minLineLength=hough_min_line, maxLineGap=hough_max_gap,
  )
  lines = (
    lines.reshape(-1, 4).astype(np.float64)
    if lines is not None else np.empty((0, 4))
  )

  pts = centroids[small_idx]
  areas = stats[small_idx, 4]
  dist = _line_alignment_dist(pts, lines)
  remove = small_idx[(dist >= align_tol) & (areas < area_floor)]
  if remove.size == 0:
    return binary

  out = binary.copy()
  out[np.isin(labels, remove)] = 0
  return out


def remove_unaligned_noise_v2(
  binary: np.ndarray,
  fog_img: np.ndarray,
  cell: int = _GRID_CELL_PX,
  hough_thr: int = _NOISE_V2_HOUGH_THR,
  hough_min_line: int = _NOISE_V2_HOUGH_MIN_LINE,
  hough_max_gap: int = _NOISE_V2_HOUGH_MAX_GAP,
  align_tol: float = _ALIGN_TOL_PX,
  method: str = "threshold",
  classifier=None,
  cov_frac_thr: float = _NOISE_V2_COV_FRAC_THR,
  max_gap_thr_px: float = _NOISE_V2_MAX_GAP_THR_PX,
) -> np.ndarray:
  """Like ``remove_unaligned_noise``, but a small component survives
  only if it's aligned with a Hough segment the noise classifier
  considers a real track -- not just aligned with *any* detected
  line, real or junk (the original function's only check). Segment
  quality itself is judged by ``module.track_classifier``, trained
  on manual true/false labels (see that module's docstring and
  analysis-note.md 2026-07-18).

  ``method="threshold"``: two hand-picked cutoffs (cov_frac, max_gap
  -- how much of the segment's own length is actually covered by
  foreground pixels, and the longest single gap along it). No model
  file needed, but noticeably weaker (precision 58.7%/recall 89.7% on
  the full labelled set).

  ``method="classifier"``: a fitted sklearn pipeline (see
  ``track_classifier.train_classifier``) scores each segment on 6
  features instead of 2. Stronger (leave-one-tile-out precision
  73-93%, recall 53-96%) but the caller must train/supply one --
  this function does not train its own, so the same classifier can
  be reused across every slice in a tile instead of refit per call.
  """
  n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
    binary, connectivity=8
  )
  small_idx = np.array([
    lbl for lbl in range(1, n_labels)
    if stats[lbl][4] > 0 and max(stats[lbl][2], stats[lbl][3]) <= cell
  ])
  if small_idx.size == 0:
    return binary

  tracks = track_classifier.detect_lite_tracks(
    binary, fog_img, hough_thr, hough_min_line, hough_max_gap)
  if not tracks:
    return binary  # nothing to score against; leave binary untouched

  feats = track_classifier.extract_features(tracks, binary)
  if method == "classifier":
    if classifier is None:
      raise ValueError("method='classifier' requires a fitted classifier "
                        "(see track_classifier.train_classifier)")
    keep_line = classifier.predict_proba(feats)[:, 1] >= 0.5
  elif method == "threshold":
    cov_frac, max_gap = feats[:, 4], feats[:, 5]
    keep_line = (cov_frac >= cov_frac_thr) & (max_gap <= max_gap_thr_px)
  else:
    raise ValueError(f"unknown method: {method!r}")

  kept_lines = np.array([
    [t.px1, t.py1, t.px2, t.py2]
    for t, k in zip(tracks, keep_line) if k
  ], dtype=np.float64)
  if kept_lines.size == 0:
    kept_lines = np.empty((0, 4))

  pts = centroids[small_idx]
  dist = _line_alignment_dist(pts, kept_lines)
  remove = small_idx[dist >= align_tol]
  if remove.size == 0:
    return binary

  out = binary.copy()
  out[np.isin(labels, remove)] = 0
  return out


def weighted_grid_hits(
  binary: np.ndarray, intensity: np.ndarray, cell: int = _GRID_CELL_PX,
) -> np.ndarray:
  """Return (cx, cy, n) hits: connected components for grouping, then one
  intensity-weighted hit per occupied ``cell`` x ``cell`` cell *within*
  each component.

  Connected-component labelling (``cv2.connectedComponentsWithStats``) is
  a basic connectivity primitive -- not shape/line clustering -- used only
  to make sure a cell's pixels all come from one physical grain/track, not
  two disconnected ones that happen to sit close together (this matters
  most right at a real vertex, where several tracks converge). Within each
  component, cells cap how much of it can collapse into one hit, so a
  long, continuously-connected track still gets re-sampled every ``cell``
  px along its length instead of becoming a single point.

  For components larger than ``cell`` (i.e. real tracks, not single
  grains), the binary blob is first thinned to a 1-px medial-axis
  skeleton (``skimage.morphology.skeletonize``) before cell sampling, so
  each hit's *position* is drawn from the track's centreline rather than
  its full width. This matters because ``detectlseg_smallregion``'s own
  straightness tolerance is tight (TH=1.5-2 px) -- real track width after
  fog/Otsu binarisation measured ~13-16 px locally (analysis-note.md,
  2026-07-12), 4-8x wider than that tolerance, which fragments tracks
  into many short segments and can even crash downstream MATLAB code
  (``integrate_smallregions``) on degenerate polylines. ``n`` (the
  occupied *original-mask* pixel count per cell, not skeleton-pixel
  count) still reflects local grain density, matching ``mabiki.m``'s own
  hit-count convention.
  """
  n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
    binary, connectivity=8
  )
  out = []
  for lbl in range(1, n_labels):
    x, y, w, h, area = stats[lbl]
    if area <= 0:
      continue
    sub_mask = labels[y:y + h, x:x + w] == lbl
    sub_intensity = (
      intensity[y:y + h, x:x + w].astype(np.float64) * sub_mask
    )
    if max(w, h) <= cell:
      cx, cy = _weighted_centroid(sub_intensity, sub_mask, x, y)
      out.append((cx, cy, float(area)))
      continue
    skel = skeletonize(sub_mask)
    skel_intensity = (
      intensity[y:y + h, x:x + w].astype(np.float64) * skel
    )
    for gy in range(0, h, cell):
      for gx in range(0, w, cell):
        n_px = int(sub_mask[gy:gy + cell, gx:gx + cell].sum())
        if n_px == 0:
          continue
        skel_blk_mask = skel[gy:gy + cell, gx:gx + cell]
        if not skel_blk_mask.any():
          # cell has real-blob pixels but no skeleton pixel (can happen
          # right at a skeleton branch gap); fall back to the blob mean.
          skel_blk_mask = sub_mask[gy:gy + cell, gx:gx + cell]
          skel_blk_int = sub_intensity[gy:gy + cell, gx:gx + cell]
        else:
          skel_blk_int = skel_intensity[gy:gy + cell, gx:gx + cell]
        cx, cy = _weighted_centroid(skel_blk_int, skel_blk_mask, x + gx, y + gy)
        out.append((cx, cy, float(n_px)))
  if not out:
    return np.empty((0, 3), dtype=np.float64)
  return np.array(out, dtype=np.float64)


def export_hits_grid(
  json_path: Path | str,
  fog_ksize: int = _FOG_KSIZE,
  noise_amin: int = _NOISE_AMIN,
  noise_amax: int = _NOISE_AMAX,
  noise_cmp: int = _NOISE_CMP,
  noise_amax_upper: int = _NOISE_AMAX_UPPER,
  cell: int = _GRID_CELL_PX,
  denoise_method: str = "legacy",
  classifier=None,
) -> np.ndarray:
  """Build the MATLAB hit pixel list ``pl`` (N x 6) via component-grouped
  grid binning (see ``weighted_grid_hits``).

  Each slice is binarized independently, then reduced to one
  intensity-weighted hit per occupied ``cell``-px cell within each
  connected component. Cuts the KISO tile's point count from 12.36M raw
  pixels to ~130k (~95x): a full 256-region ``detectlseg_smallregion`` run
  completed in 5.5h (see analysis-note.md, 2026-07-12). ``n`` is the
  occupied pixel count per hit.

  ``denoise_method`` selects the per-slice binary noise filter before
  hit extraction:
  - ``"off"``: no filtering.
  - ``"legacy"`` (default): ``remove_unaligned_noise`` (Hough-line
    alignment + area floor, no manual labels involved).
  - ``"threshold"``: ``remove_unaligned_noise_v2`` with hand-picked
    cov_frac/max_gap cutoffs (needs no model, weaker than below).
  - ``"classifier"``: ``remove_unaligned_noise_v2`` scored by a
    trained ``track_classifier`` model, passed in via ``classifier``
    (train once with ``track_classifier.train_classifier`` and reuse
    across every slice -- refitting per slice would be needlessly
    slow and would let each slice silently use a slightly different
    decision boundary).
  """
  if denoise_method == "classifier" and classifier is None:
    raise ValueError(
      "denoise_method='classifier' requires a fitted classifier "
      "(see track_classifier.train_classifier)")
  reader = load_spng(json_path)
  cols = []
  for z in range(len(reader)):
    fog, binary = _binarize_slice(
      reader, z, fog_ksize, noise_amin, noise_amax, noise_cmp,
      noise_amax_upper,
    )
    if denoise_method == "legacy":
      binary = remove_unaligned_noise(binary, cell=cell)
    elif denoise_method in ("threshold", "classifier"):
      binary = remove_unaligned_noise_v2(
        binary, fog, cell=cell, method=denoise_method,
        classifier=classifier)
    elif denoise_method != "off":
      raise ValueError(f"unknown denoise_method: {denoise_method!r}")
    hits = weighted_grid_hits(binary, fog, cell)
    if hits.shape[0] == 0:
      continue
    block = np.empty((len(hits), len(_PL_VARNAMES)), dtype=np.float64)
    block[:, 0] = hits[:, 0] + _ORIGIN_OFFSET    # x = col
    block[:, 1] = hits[:, 1] + _ORIGIN_OFFSET    # y = row
    block[:, 2] = z + _ORIGIN_OFFSET             # z = slice index
    block[:, 3] = hits[:, 2]                     # occupied px count
    block[:, 4] = _SHEET_PLACEHOLDER
    block[:, 5] = _ID_PLACEHOLDER
    cols.append(block)
  if not cols:
    return np.empty((0, len(_PL_VARNAMES)), dtype=np.float64)
  return np.concatenate(cols, axis=0)


def save_mat(pl: np.ndarray, out_path: Path | str) -> None:
  """Write ``pl`` and its variable names to a MATLAB ``.mat`` file."""
  out = Path(out_path)
  out.parent.mkdir(parents=True, exist_ok=True)
  savemat(
    str(out),
    {"pl": pl, "variablenamespl": np.array(_PL_VARNAMES, dtype=object)},
    do_compression=True,
  )


def _default_out(json_path: Path) -> Path:
  return json_path.with_name(json_path.stem + "_pl.mat")


def main(argv: list[str] | None = None) -> int:
  p = argparse.ArgumentParser(
    description="Export a tile as a 3-D hit list (.mat) for MATLAB."
  )
  p.add_argument("input", type=Path, help="tile JSON metadata path")
  p.add_argument(
    "-o", "--output", type=Path, default=None,
    help="output .mat path (default: <stem>_pl.mat next to input)",
  )
  p.add_argument(
    "--mode", choices=[_MODE_GRID, _MODE_PIXEL], default=_DEFAULT_MODE,
    help="grid: one intensity-weighted hit per occupied cell (default, "
         "~95x sparser, safe for long/connected tracks); "
         "pixel: one hit per raw binary pixel (dense, for comparison)",
  )
  p.add_argument(
    "--cell-px", type=int, default=_GRID_CELL_PX,
    help="grid mode: spatial bin size in px (default: %(default)s)",
  )
  p.add_argument(
    "--denoise-method",
    choices=["off", "legacy", "threshold", "classifier"],
    default="legacy",
    help="grid mode: 'off' keeps all small components; 'legacy' is "
         "the original Hough-alignment+area-floor filter (default); "
         "'threshold'/'classifier' use track_classifier, trained on "
         "manual labels in results/manual_labels/ (see that module's "
         "docstring) -- 'classifier' is the stronger of the two but "
         "needs enough labelled data to fit",
  )
  p.add_argument(
    "--labels-dir", type=Path, default=_DEFAULT_LABELS_DIR,
    help="manual_labels/ dir for --denoise-method classifier "
         "(default: %(default)s)",
  )
  p.add_argument("--fog-ksize", type=int, default=_FOG_KSIZE)
  p.add_argument("--noise-amin", type=int, default=_NOISE_AMIN)
  p.add_argument("--noise-amax", type=int, default=_NOISE_AMAX)
  p.add_argument("--noise-cmp", type=int, default=_NOISE_CMP)
  p.add_argument("--noise-amax-upper", type=int, default=_NOISE_AMAX_UPPER)
  args = p.parse_args(argv)

  out = args.output or _default_out(args.input)
  common = dict(
    fog_ksize=args.fog_ksize,
    noise_amin=args.noise_amin,
    noise_amax=args.noise_amax,
    noise_cmp=args.noise_cmp,
    noise_amax_upper=args.noise_amax_upper,
  )
  if args.mode == _MODE_GRID:
    classifier = None
    if args.denoise_method == "classifier":
      X, y = track_classifier.build_training_set(args.labels_dir)
      classifier = track_classifier.train_classifier(X, y)
      if classifier is None:
        p.error(
          f"not enough labelled data in {args.labels_dir} to train a "
          "classifier (need >=20 decisions with both true and false)")
    pl = export_hits_grid(
      args.input, cell=args.cell_px, denoise_method=args.denoise_method,
      classifier=classifier, **common
    )
  else:
    pl = export_hits(args.input, **common)
  save_mat(pl, out)
  print(f"wrote {len(pl)} hits -> {out}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
