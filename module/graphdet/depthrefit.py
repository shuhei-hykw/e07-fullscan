"""Per-polyline depth refit after stage 2 (not in the MATLAB original).

A track out of focus still darkens the slices a few steps above and
below it, so a clean point cloud (the RS mask) gives stage 2 copies of
a track at the wrong depth, and sometimes only such a copy. This moves
each whole polyline in z, by up to MAX_DZ slices, to the depth where
the mean darkness along it peaks, when that beats its own depth by
more than ``min_gain``. Its shape and x/y are kept; nothing is dropped
(removing the duplicates that end up on top of each other lost real
coverage on tune, discussion.md 2026-10-29).
"""
from __future__ import annotations

import cv2
import numpy as np

from module.preprocess import fog_remove

from .support import sample

MAX_DZ = 5
# Polyline sampling step (z-scaled px) for the darkness profile
STEP_PX = 1.0
# Darkness is the fog-removed slice averaged over this box (px)
DARK_BOX_PX = 3
# A shift is tried only where this share of the samples stays inside
# the stack.
MIN_INSIDE = 0.8
# Default gain (fog-removed grey levels), middle of the tune plateau
MIN_GAIN = 2.0


def darkness_stack(reader, lo: int = 0, hi: int | None = None
                   ) -> np.ndarray:
  """(slices, rows, cols) float32 darkness: box-averaged fog_remove."""
  hi = len(reader) if hi is None else hi
  box = (DARK_BOX_PX, DARK_BOX_PX)
  return np.stack([cv2.blur(fog_remove(reader.read(z)).astype(np.float32),
                            box) for z in range(lo, hi)])


def refit_depth(polys: list, dark: np.ndarray, z_scale: float,
                min_gain: float = MIN_GAIN, offset: float = 0.0
                ) -> tuple[list, np.ndarray]:
  """Shifted polylines and the shift (slices) of each.

  ``polys`` are (n, 3) x, y, slice arrays in the coordinates of
  ``dark`` plus ``offset`` (1 for export coordinates). Ties go to the
  smaller shift.
  """
  if not polys:
    return [], np.zeros(0, int)
  nz, ny, nx = dark.shape
  dzs = np.array(sorted(range(-MAX_DZ, MAX_DZ + 1), key=abs))
  pts, pid = sample([p - offset for p in polys], z_scale, STEP_PX)
  xi = np.clip(np.round(pts[:, 0]).astype(int), 0, nx - 1)
  yi = np.clip(np.round(pts[:, 1]).astype(int), 0, ny - 1)
  z0 = np.round(pts[:, 2]).astype(int)
  n_poly = len(polys)
  count = np.bincount(pid, minlength=n_poly)
  in0 = (z0 >= 0) & (z0 < nz)
  d0 = np.zeros(len(pts))
  d0[in0] = dark[z0[in0], yi[in0], xi[in0]]
  # Gain of each shift over the polyline's own depth, on the samples
  # inside the stack at both depths, so that losing edge samples does
  # not count as a gain. Too few such samples (or too few at the own
  # depth): no gain.
  gain = np.full((len(dzs), n_poly), -np.inf)
  for k, dz in enumerate(dzs):
    zi = z0 + dz
    ok = in0 & (zi >= 0) & (zi < nz)
    v = np.zeros(len(pts))
    v[ok] = dark[zi[ok], yi[ok], xi[ok]] - d0[ok]
    s = np.bincount(pid, v, n_poly)
    n = np.bincount(pid[ok], minlength=n_poly)
    use = n >= MIN_INSIDE * count
    gain[k, use] = s[use] / n[use]
  best = np.argmax(gain, axis=0)
  top = gain[best, np.arange(n_poly)]
  shift = np.where(top > min_gain, dzs[best], 0)
  return [p + [0, 0, s] for p, s in zip(polys, shift)], shift
