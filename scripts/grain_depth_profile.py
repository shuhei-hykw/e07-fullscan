"""Depth profile of isolated grains: how fast a grain fades with focus.

Needs no truth, so real and synthetic stacks are measured the same way.
A grain is a dog3d hit (eval_pointcloud) with no other DoG maximum
within ISO_R_PX in xy over ISO_DZ slices either side; its profile is the
DoG response, maximum over a (2 PEAK_HALF_PX + 1)^2 box at its xy,
in the slices within PROFILE_HALF of it, divided by its peak. The depth
FWHM (slices) is read off each profile by linear interpolation; grains
whose profile does not fall under half on both sides inside the window
are counted (open_frac) but get no FWHM.

  python scripts/grain_depth_profile.py STACK [STACK ...] \
    [--out results/pointcloud_eval/depth_profile.csv]

STACK is a stack's JSON or a directory holding image.json. Prints per stack the number of grains, the
median FWHM and the median profile; writes the per-stack summary CSV.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import maximum_filter
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_pointcloud as ep                                  # noqa: E402
from module.reader import load_spng                           # noqa: E402

ISO_R_PX = 10
ISO_DZ = 3
PROFILE_HALF = 8
PEAK_HALF_PX = 1
EDGE_PX = 16
HALF = 0.5
# Grains per stack used (the brightest isolated ones are not preferred:
# a random subset keeps faint grains in)
MAX_GRAINS = 3000
SEED = 20261026


def responses(reader):
  """DoG response of every slice, (S, H, W) float32."""
  return np.stack([ep.dog_response(reader.read(s))
                   for s in range(len(reader))])


def fwhm(prof):
  """Width at half maximum around the centre sample, or NaN if open."""
  c = PROFILE_HALF
  lo = hi = None
  for i in range(c, 0, -1):
    if prof[i - 1] < HALF <= prof[i]:
      lo = i - (prof[i] - HALF) / (prof[i] - prof[i - 1])
      break
  for i in range(c, len(prof) - 1):
    if prof[i + 1] < HALF <= prof[i]:
      hi = i + (prof[i] - HALF) / (prof[i] - prof[i + 1])
      break
  return np.nan if lo is None or hi is None else hi - lo


def measure(stack_dir, k=None):
  p = Path(stack_dir)
  reader = load_spng(p if p.suffix == ".json" else p / "image.json")
  r = responses(reader)
  n, h, w = r.shape
  hits, _ = ep.dog_hits(reader, k)
  peaks = hits["dog"]
  grains = hits["dog3d"].astype(int)
  tree = cKDTree(peaks[:, :2])
  ok = ((grains[:, 0] >= EDGE_PX) & (grains[:, 0] < w - EDGE_PX)
        & (grains[:, 1] >= EDGE_PX) & (grains[:, 1] < h - EDGE_PX)
        & (grains[:, 2] >= PROFILE_HALF)
        & (grains[:, 2] < n - PROFILE_HALF))
  iso = np.zeros(len(grains), bool)
  for i in np.flatnonzero(ok):
    nb = tree.query_ball_point(grains[i, :2], ISO_R_PX)
    dz = np.abs(peaks[nb, 2] - grains[i, 2])
    d = np.hypot(*(peaks[nb, :2] - grains[i, :2]).T)
    iso[i] = not ((dz <= ISO_DZ) & (d > PEAK_HALF_PX + 1)).any()
  idx = np.flatnonzero(iso)
  rng = np.random.default_rng(SEED)
  if idx.size > MAX_GRAINS:
    idx = np.sort(rng.choice(idx, MAX_GRAINS, replace=False))
  box = maximum_filter(r, size=(1, 2 * PEAK_HALF_PX + 1,
                                2 * PEAK_HALF_PX + 1))
  offs = np.arange(-PROFILE_HALF, PROFILE_HALF + 1)
  x, y, z = grains[idx, 0], grains[idx, 1], grains[idx, 2]
  prof = box[z[:, None] + offs[None, :], y[:, None], x[:, None]]
  prof = prof / prof[:, PROFILE_HALF:PROFILE_HALF + 1]
  widths = np.array([fwhm(p) for p in prof])
  row = {"stack": str(stack_dir), "n_grains": int(idx.size),
         "fwhm_med": float(np.nanmedian(widths)),
         "fwhm_p25": float(np.nanquantile(widths, 0.25)),
         "fwhm_p75": float(np.nanquantile(widths, 0.75)),
         "open_frac": float(np.isnan(widths).mean())}
  for o, v in zip(offs, np.median(prof, axis=0)):
    row[f"prof{o:+d}"] = float(v)
  return row


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("stacks", nargs="+", type=Path)
  ap.add_argument("--dog-k", type=float, default=ep.DOG_K)
  ap.add_argument("--out", type=Path,
                  default=Path("results/pointcloud_eval/depth_profile.csv"))
  args = ap.parse_args()
  rows = []
  for s in args.stacks:
    rows.append(measure(s, args.dog_k))
    print({k: (round(v, 3) if isinstance(v, float) else v)
           for k, v in rows[-1].items()}, flush=True)
  args.out.parent.mkdir(parents=True, exist_ok=True)
  pd.DataFrame(rows).to_csv(args.out, index=False)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
