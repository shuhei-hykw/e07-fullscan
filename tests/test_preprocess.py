"""Regression tests for the extracted branch-neutral preprocessing module.

Proves the extraction is behavior-preserving: the new
`module.preprocess.preprocess` matches a frozen copy of the old
`tracking._finder.preprocess`, and `remove_noise(noise_amax_upper=0)` matches
the server's old 2-branch noise filter, on a synthetic image.
"""
import cv2
import numpy as np

from module.preprocess import preprocess, remove_noise


def _synthetic() -> np.ndarray:
  """Bright background with dark tracks and dark blobs of varied size."""
  img = np.full((256, 256), 200, dtype=np.uint8)
  # dark tracks (foreground = dark grains on emulsion)
  cv2.line(img, (30, 40), (200, 60), 40, 2)
  cv2.line(img, (40, 200), (210, 120), 40, 2)
  cv2.line(img, (120, 30), (130, 220), 40, 2)
  # small specks and one large blob (exercise all noise branches)
  for cx, cy in [(70, 150), (160, 180), (90, 90), (175, 70)]:
    cv2.circle(img, (cx, cy), 2, 40, -1)
  cv2.circle(img, (210, 210), 22, 40, -1)
  return img


def _old_preprocess(
  img, fog_ksize=51, noise_amin=2, noise_amax=100,
  noise_cmp=50, noise_amax_upper=0,
):
  """Frozen copy of the pre-extraction tracking._finder.preprocess."""
  k = fog_ksize if fog_ksize % 2 == 1 else fog_ksize + 1
  blurred = cv2.GaussianBlur(img, (k, k), 0)
  current = cv2.subtract(blurred, img)
  _, current = cv2.threshold(
    current, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
  )
  contours, _ = cv2.findContours(
    current, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
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
  cv2.drawContours(current, noise, -1, 0, thickness=-1)
  return current


def _old_server_noise(binary, noise_amin=2, noise_amax=100, noise_cmp=50):
  """Frozen copy of the pre-extraction server 2-branch noise filter."""
  current = binary.copy()
  cnts, _ = cv2.findContours(
    current, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
  )
  noise = []
  for cnt in cnts:
    area = cv2.contourArea(cnt)
    if area < noise_amin:
      noise.append(cnt)
      continue
    perimeter = cv2.arcLength(cnt, True)
    if (perimeter > 0 and area < noise_amax
        and (perimeter ** 2) / area < noise_cmp):
      noise.append(cnt)
  cv2.drawContours(current, noise, -1, 0, thickness=-1)
  return current


def test_preprocess_matches_old_default():
  img = _synthetic()
  assert np.array_equal(preprocess(img), _old_preprocess(img))


def test_preprocess_matches_old_with_amax_upper():
  img = _synthetic()
  new = preprocess(img, noise_amax_upper=300)
  old = _old_preprocess(img, noise_amax_upper=300)
  assert np.array_equal(new, old)


def test_remove_noise_matches_old_server_filter():
  """remove_noise(amax_upper=0) == server's old 2-branch filter."""
  img = _synthetic()
  k = 51
  binary = cv2.threshold(
    cv2.subtract(cv2.GaussianBlur(img, (k, k), 0), img),
    0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU,
  )[1]
  new = remove_noise(binary, noise_amax_upper=0)
  old = _old_server_noise(binary)
  assert np.array_equal(new, old)


def test_amax_upper_removes_large_blob():
  """The large blob survives the default filter but is removed by amax_upper."""
  img = _synthetic()
  base = preprocess(img, noise_amax_upper=0)
  capped = preprocess(img, noise_amax_upper=300)
  # capping at 300 px^2 removes the big blob -> strictly fewer foreground px
  assert capped.sum() < base.sum()
