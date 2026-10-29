"""Vertex candidates of a view: method A plus the darkest graph-detector
(B') branch points (adopted 2026-10-29 after the evalU gate; rule frozen
in discussion.md 2026-10-28 16:49, same definitions as
e07-g4-hypernuclei module/rankstudy.py, which scored it).

- every method-A candidate of the view (production cuts), plus
- the TOP_K B' branch points with the highest local darkness: the
  minimum projection over +-DARK_HALF_SLICES slices around the point,
  minus its Gaussian background (sigma BG_SIGMA_PX), averaged over the
  (2 DARK_RADIUS_PX + 1)^2 px square around it, clipped at the image
  edge. Ties are broken at random with a fixed seed, never by order.
No grouping and no refill: the union keeps both lists as they are.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TOP_K = 770
DARK_HALF_SLICES = 3
DARK_RADIUS_PX = 6
BG_SIGMA_PX = 8.0
TIE_SEED = 0
# B' points sit on whole or half slices; snap away float noise so that a
# half slice always rounds the same way (to even). e07-g4-hypernuclei
# derives the slice from its float32 stage step, so on half slices its
# rounding follows that noise: a few of 770 picks per view differ.
SLICE_DECIMALS = 6


def gaussian_blur(img: np.ndarray, sigma: float) -> np.ndarray:
  """Periodic Gaussian blur by FFT (as imagestats.gaussian_blur)."""
  n, m = img.shape
  fy = np.fft.fftfreq(n)[:, None]
  fx = np.fft.rfftfreq(m)[None, :]
  k = np.exp(-2.0 * np.pi ** 2 * sigma ** 2 * (fx ** 2 + fy ** 2))
  return np.fft.irfft2(np.fft.rfft2(img) * k, s=img.shape)


def local_darkness(stack: np.ndarray, xy: np.ndarray,
                   slices: np.ndarray) -> np.ndarray:
  """Darkness of each point (x, y in px, slice index rounded to the
  nearest slice, half slices to even) in a raw (slices, rows, cols)
  stack."""
  n = stack.shape[0]
  r = DARK_RADIUS_PX
  out = np.zeros(len(xy))
  cache = {}
  for i, ((x, y), k) in enumerate(zip(xy, slices)):
    k = int(np.clip(round(round(float(k), SLICE_DECIMALS)), 0, n - 1))
    if k not in cache:
      lo, hi = max(0, k - DARK_HALF_SLICES), min(n, k + DARK_HALF_SLICES + 1)
      mp = stack[lo:hi].min(axis=0).astype(float)
      cache[k] = gaussian_blur(mp, BG_SIGMA_PX) - mp
    det = cache[k]
    yi, xi = int(round(y)), int(round(x))
    win = det[max(0, yi - r):yi + r + 1, max(0, xi - r):xi + r + 1]
    out[i] = win.mean() if win.size else 0.0
  return out


def top_k(score: np.ndarray, k: int, seed: int = TIE_SEED) -> np.ndarray:
  """Indices of the k highest scores, ties broken at random."""
  key = np.random.default_rng(seed).random(len(score))
  return np.lexsort((key, -np.asarray(score, dtype=float)))[:k]


def stage_to_slice(z_mm: np.ndarray, z_positions: np.ndarray
                   ) -> np.ndarray:
  """Fractional slice index of stage z (mm), either stack direction."""
  z = np.asarray(z_positions, float)
  idx = np.arange(len(z), dtype=float)
  if z[-1] < z[0]:
    z, idx = z[::-1], idx[::-1]
  return np.interp(z_mm, z, idx)


def union_candidates(a: pd.DataFrame, b: pd.DataFrame, stack: np.ndarray,
                     z_positions: np.ndarray, k: int = TOP_K
                     ) -> pd.DataFrame:
  """A rows (source "A") followed by the top-k B' rows (source "Bprime",
  with their darkness and rank). B' needs vx_px, vy_px and z_mean
  (stage mm)."""
  a = a.assign(source="A")
  if b.empty:
    return a
  sl = stage_to_slice(b["z_mean"].to_numpy(), z_positions)
  dark = local_darkness(stack, b[["vx_px", "vy_px"]].to_numpy(), sl)
  idx = top_k(dark, k)
  top = b.iloc[idx].assign(source="Bprime", darkness=dark[idx],
                           dark_rank=np.arange(len(idx)))
  return pd.concat([a, top], ignore_index=True)
