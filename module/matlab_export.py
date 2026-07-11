"""Export a tile as a 3-D hit-pixel list for the MATLAB graph detector.

Bridges the Python full-scan pipeline to the graph-theory event detector in
``e07/matlab`` (``detect_tracks.m`` + helpers). That detector's stage-1 input
is a 3-D hit pixel list ``pl = {x, y, z, n, sheet, id}`` (x, y in pixels,
z = slice index); its downstream stages only use ``dspl = mabiki(pl, 3)``.

Unlike the Hough pipeline, which z-projects the stack into one 2-D image, the
graph detector needs the full z extent. So each slice is binarized
independently (fog removal -> Otsu -> noise removal, reused from
``module.preprocess``) and every foreground pixel becomes one 3-D hit.

Coordinates are 1-based (x = col + 1, y = row + 1, z = slice + 1) to match the
MATLAB convention of a (1, 1, 1) origin and its ``x > lb`` small-region split.

The block-3 down-sampling (``mabiki``) is intentionally left to MATLAB; this
writer emits the raw ``pl`` only.

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


def export_hits(
  json_path: Path | str,
  fog_ksize: int = _FOG_KSIZE,
  noise_amin: int = _NOISE_AMIN,
  noise_amax: int = _NOISE_AMAX,
  noise_cmp: int = _NOISE_CMP,
  noise_amax_upper: int = _NOISE_AMAX_UPPER,
) -> np.ndarray:
  """Build the MATLAB hit pixel list ``pl`` (N x 6) for one tile.

  Each slice is binarized independently; foreground pixels become 3-D hits
  with intensity ``n`` taken from the fog-removed image.
  """
  reader = load_spng(json_path)
  cols = []
  for z in range(len(reader)):
    img = reader.read(z)
    fog = fog_remove(img, fog_ksize)
    _, binary = otsu_binarize(fog)
    binary = remove_noise(
      binary, noise_amin, noise_amax, noise_cmp, noise_amax_upper
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
  p.add_argument("--fog-ksize", type=int, default=_FOG_KSIZE)
  p.add_argument("--noise-amin", type=int, default=_NOISE_AMIN)
  p.add_argument("--noise-amax", type=int, default=_NOISE_AMAX)
  p.add_argument("--noise-cmp", type=int, default=_NOISE_CMP)
  p.add_argument("--noise-amax-upper", type=int, default=_NOISE_AMAX_UPPER)
  args = p.parse_args(argv)

  out = args.output or _default_out(args.input)
  pl = export_hits(
    args.input,
    fog_ksize=args.fog_ksize,
    noise_amin=args.noise_amin,
    noise_amax=args.noise_amax,
    noise_cmp=args.noise_cmp,
    noise_amax_upper=args.noise_amax_upper,
  )
  save_mat(pl, out)
  print(f"wrote {len(pl)} hits -> {out}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
