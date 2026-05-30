"""Branch-neutral image preprocessing through step-5 noise removal.

This is the shared preprocessing boundary before the pipeline branches into
conventional Hough track/vertex detection and any future graph/topology
analysis. Both the batch tracking path and the diagnostic viewer call these
functions so that what the viewer previews matches what the batch pipeline
computes.

Stages: fog removal -> Otsu threshold -> noise removal (connected-component
area filter).
"""
from __future__ import annotations

import cv2
import numpy as np

# Defaults mirror config/default.yaml (viewer block).
_FOG_KSIZE        = 51
_NOISE_AMIN       = 2
_NOISE_AMAX       = 100
_NOISE_CMP        = 50
_NOISE_AMAX_UPPER = 0   # 0 = disabled; >0 removes blobs larger than this


def fog_remove(img: np.ndarray, fog_ksize: int = _FOG_KSIZE) -> np.ndarray:
  """Return the fog-removed image (blurred background subtracted).

  Used both as the Otsu input and as the intensity-measurement image, so it
  must stay a single implementation.
  """
  k = fog_ksize if fog_ksize % 2 == 1 else fog_ksize + 1
  blurred = cv2.GaussianBlur(img, (k, k), 0)
  return cv2.subtract(blurred, img)


def otsu_binarize(img: np.ndarray) -> tuple[float, np.ndarray]:
  """Otsu threshold. Returns (threshold_value, binary image)."""
  otsu_val, binary = cv2.threshold(
    img, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
  )
  return float(otsu_val), binary


def remove_noise(
  binary: np.ndarray,
  noise_amin: int = _NOISE_AMIN,
  noise_amax: int = _NOISE_AMAX,
  noise_cmp: int  = _NOISE_CMP,
  noise_amax_upper: int = _NOISE_AMAX_UPPER,
) -> np.ndarray:
  """Remove noise blobs from a binary image by connected-component area.

  Three branches, evaluated per contour:
    area < noise_amin                         -> remove (specks)
    noise_amax_upper > 0 and area > upper     -> remove (large artifacts:
                                                 emulsion folds, grain clusters)
    area < noise_amax and peri^2/area < cmp   -> remove (compact small blobs)
  Operates in place on a copy and returns it.
  """
  out = binary.copy()
  contours, _ = cv2.findContours(
    out, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
  )
  noise = []
  for cnt in contours:
    area = cv2.contourArea(cnt)
    if area < noise_amin:
      noise.append(cnt)
      continue
    if noise_amax_upper > 0 and area > noise_amax_upper:
      noise.append(cnt)
      continue
    perimeter = cv2.arcLength(cnt, True)
    if (perimeter > 0 and area < noise_amax
        and (perimeter ** 2) / area < noise_cmp):
      noise.append(cnt)
  cv2.drawContours(out, noise, -1, 0, thickness=-1)
  return out


def preprocess(
  img: np.ndarray,
  fog_ksize: int  = _FOG_KSIZE,
  noise_amin: int = _NOISE_AMIN,
  noise_amax: int = _NOISE_AMAX,
  noise_cmp: int  = _NOISE_CMP,
  noise_amax_upper: int = _NOISE_AMAX_UPPER,
) -> np.ndarray:
  """Fog removal -> Otsu threshold -> noise removal. Returns binary image.

  noise_amax_upper > 0: also remove blobs with area > noise_amax_upper
  (large artifacts such as emulsion folds or grain clusters).
  """
  fog = fog_remove(img, fog_ksize)
  _, binary = otsu_binarize(fog)
  return remove_noise(
    binary, noise_amin, noise_amax, noise_cmp, noise_amax_upper
  )
