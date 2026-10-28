"""Two-scale ridge mask ("RS"): an alternative to the Otsu mask that puts
hits along streaks instead of on blobs (point-placement candidate,
discussion.md 2026-10-28 10:58; experimental, production stays Otsu).

A pixel is kept when either oriented line filter on the fog-removed
slice exceeds its robust threshold:
- a long kernel (sigma 2.5 px across, 12 px along) at LONG_K sigmas;
- a short kernel (4 px along) for tracks shorter than the long one, at
  the stricter SHORT_K sigmas.
The union then goes through the same small-component filter as the
Otsu mask (``preprocess.remove_noise``).
"""
from __future__ import annotations

import cv2
import numpy as np

from module.preprocess import remove_noise

SIGMA_CROSS_PX = 2.5
LONG_SIGMA_ALONG_PX = 12.0
SHORT_SIGMA_ALONG_PX = 4.0
N_ANGLES = 16
# Kernel half-width in units of the along sigma.
KERNEL_HALF_SIGMAS = 3
LONG_K = 3.0
SHORT_K = 4.0
MAD_TO_SIGMA = 1.4826


def line_kernels(sigma_along: float) -> list[np.ndarray]:
  """Zero-mean ridge kernels (Mexican hat across, Gaussian along), one
  per direction, each normalised to unit absolute sum."""
  half = int(KERNEL_HALF_SIGMAS * sigma_along)
  y, x = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float32)
  out = []
  for th in np.linspace(0, np.pi, N_ANGLES, endpoint=False):
    u = x * np.cos(th) + y * np.sin(th)
    v = -x * np.sin(th) + y * np.cos(th)
    vv = v * v / SIGMA_CROSS_PX ** 2
    k = (1 - vv) * np.exp(-u * u / (2 * sigma_along ** 2) - vv / 2)
    k -= k.mean()
    out.append(k / np.abs(k).sum())
  return out


_LONG = line_kernels(LONG_SIGMA_ALONG_PX)
_SHORT = line_kernels(SHORT_SIGMA_ALONG_PX)


def _response(f: np.ndarray, kernels: list[np.ndarray]) -> np.ndarray:
  return np.max([cv2.filter2D(f, -1, k) for k in kernels], axis=0)


def _above(r: np.ndarray, k: float) -> np.ndarray:
  med = np.median(r)
  sig = MAD_TO_SIGMA * np.median(np.abs(r - med))
  return ((r > med + k * sig) * 255).astype(np.uint8)


def rs_mask(fog: np.ndarray) -> np.ndarray:
  """Binary (0/255 uint8) RS mask of one fog-removed slice."""
  f = fog.astype(np.float32)
  return remove_noise(_above(_response(f, _LONG), LONG_K)
                      | _above(_response(f, _SHORT), SHORT_K))
