"""Port of mabiki.m: thin a hit-pixel list onto a coarser grid.

``detect_tracks.m`` runs everything downstream on ``mabiki(pl, 3)``,
not on the raw pixels: one representative hit per n x n block of each
slice, placed at the centroid of the block's occupied pixels and
carrying how many there were. Blocks are in x and y only -- z keeps
its full slice resolution.

This matters for calibration as much as for speed. The block size sets
the spacing between hits along a track, and most of the detector's
distance constants were tuned at the simulation's n = 3. The real E07
export samples at 30 px (matlab_export._GRID_CELL_PX), so being able
to re-thin the simulation at other block sizes is what lets the two be
compared on equal terms.
"""
from __future__ import annotations

import numpy as np

_DEFAULT_BLOCK = 3


def mabiki(hits: np.ndarray, n: int = _DEFAULT_BLOCK) -> np.ndarray:
  """Return (M, 4): x, y, z, and the pixel count behind each hit.

  ``hits`` are integer pixel coordinates; MATLAB rasterises them into
  a boolean image first, so a pixel listed twice counts once.
  """
  p = np.unique(np.asarray(hits, dtype=np.int64)[:, :3], axis=0)
  if p.shape[0] == 0:
    return np.zeros((0, 4))
  lo = p[:, :2].min(axis=0)
  block = np.column_stack([(p[:, :2] - lo) // n, p[:, 2]])
  _, inv, counts = np.unique(
    block, axis=0, return_inverse=True, return_counts=True)
  weight = counts.astype(float)
  out = np.column_stack([
    np.bincount(inv, p[:, 0].astype(float)) / weight,
    np.bincount(inv, p[:, 1].astype(float)) / weight,
    np.bincount(inv, p[:, 2].astype(float)) / weight,
    weight,
  ])
  # MATLAB emits blocks in image order: z slowest, then column (x),
  # then row (y). Nothing downstream depends on it, but keeping the
  # order makes a diff against a MATLAB run readable.
  return out[np.lexsort((out[:, 1], out[:, 0], out[:, 2]))]
