"""Export a tile as a 3-D hit-pixel list for the MATLAB graph detector.

Bridges the Python full-scan pipeline to the graph-theory event detector in
``e07/matlab`` (``detect_tracks.m`` + helpers). That detector's stage-1 input
is a 3-D hit pixel list ``pl = {x, y, z, n, sheet, id}`` (x, y in pixels,
z = slice index); its downstream stages only use ``dspl = mabiki(pl, 3)``.

Unlike the Hough pipeline, which z-projects the stack into one 2-D image, the
graph detector needs the full z extent. So each slice is binarized
independently (fog removal -> Otsu -> noise removal, reused from
``module.preprocess``).

Default mode (``grid``): one intensity-weighted 3-D hit per occupied
``_GRID_CELL_PX`` x ``_GRID_CELL_PX`` spatial bin (fixed grid, no
connected-component analysis). A raw-pixel mode (``pixel``, one hit per
binary pixel) is kept for comparison but is so dense it makes
``detectlseg_smallregion`` take an estimated 600+ days on real data (see
analysis-note.md, 2026-07-11 entries). An earlier connected-component
"one hit per grain blob" mode was tried and dropped: it made
``detectlseg_smallregion`` tractable (~2.5h/tile) but a long,
continuously-connected track collapses into a *single* connected
component, so its whole length -- and all its line/vertex information --
collapsed into one hit. A fixed grid has no notion of connectivity, so a
long track keeps getting re-sampled every ``_GRID_CELL_PX`` along its
length, same as an isolated grain.

Coordinates are 1-based (x = col + 1, y = row + 1, z = slice + 1) to match the
MATLAB convention of a (1, 1, 1) origin and its ``x > lb`` small-region split.

The block-3 down-sampling (``mabiki``) is intentionally left to MATLAB; this
writer emits ``pl`` only (not pre-downsampled).

  python -m module.matlab_export tile.json -o tile_pl.mat
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from scipy.io import savemat

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


def weighted_grid_hits(
  binary: np.ndarray, intensity: np.ndarray, cell: int = _GRID_CELL_PX,
) -> np.ndarray:
  """Return (cx, cy, n) per occupied ``cell`` x ``cell`` spatial bin.

  Deliberately NOT connected-component based (no ``cv2.findContours``, no
  grouping by shape/adjacency): every foreground pixel is assigned to a
  fixed grid cell by position alone, and each occupied cell yields one hit
  at the intensity-weighted centroid of its pixels. ``n`` is the occupied
  pixel count in that cell (matches ``mabiki.m``'s own hit-count
  convention).

  This intentionally re-samples every ``cell`` px along a track, however
  long or densely connected it is -- unlike a connected-component
  centroid, which would collapse an entire long track into a single
  point (see module docstring).
  """
  ys, xs = np.nonzero(binary)
  if xs.size == 0:
    return np.empty((0, 3), dtype=np.float64)
  w = intensity[ys, xs].astype(np.float64)
  bin_x = (xs // cell).astype(np.int64)
  bin_y = (ys // cell).astype(np.int64)
  ncols = binary.shape[1] // cell + 1
  key = bin_y * ncols + bin_x

  n_bins = int(key.max()) + 1
  sum_w  = np.bincount(key, weights=w, minlength=n_bins)
  sum_wx = np.bincount(key, weights=w * xs, minlength=n_bins)
  sum_wy = np.bincount(key, weights=w * ys, minlength=n_bins)
  count  = np.bincount(key, minlength=n_bins)

  occupied = count > 0
  cx = np.where(sum_w[occupied] > 0, sum_wx[occupied] / np.maximum(
    sum_w[occupied], 1e-12), 0.0)
  cy = np.where(sum_w[occupied] > 0, sum_wy[occupied] / np.maximum(
    sum_w[occupied], 1e-12), 0.0)
  return np.stack(
    [cx, cy, count[occupied].astype(np.float64)], axis=1
  )


def export_hits_grid(
  json_path: Path | str,
  fog_ksize: int = _FOG_KSIZE,
  noise_amin: int = _NOISE_AMIN,
  noise_amax: int = _NOISE_AMAX,
  noise_cmp: int = _NOISE_CMP,
  noise_amax_upper: int = _NOISE_AMAX_UPPER,
  cell: int = _GRID_CELL_PX,
) -> np.ndarray:
  """Build the MATLAB hit pixel list ``pl`` (N x 6) via fixed-grid binning.

  Each slice is binarized independently, then reduced to one
  intensity-weighted hit per occupied ``cell``-px spatial bin (see
  ``weighted_grid_hits``). Cuts the KISO tile's point count from 12.36M
  raw pixels to ~130k (~95x), keeping ``detectlseg_smallregion`` near its
  proven ~2.5h/tile run time while re-sampling every ``cell`` px along any
  track -- long tracks are not collapsed to a single point the way a
  connected-component reduction would (see module docstring). ``n`` is the
  occupied pixel count per bin.
  """
  reader = load_spng(json_path)
  cols = []
  for z in range(len(reader)):
    fog, binary = _binarize_slice(
      reader, z, fog_ksize, noise_amin, noise_amax, noise_cmp,
      noise_amax_upper,
    )
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
    pl = export_hits_grid(args.input, cell=args.cell_px, **common)
  else:
    pl = export_hits(args.input, **common)
  save_mat(pl, out)
  print(f"wrote {len(pl)} hits -> {out}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
