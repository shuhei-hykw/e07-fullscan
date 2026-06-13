#!/usr/bin/env python3
"""Step-5 (noise-removal) compatibility check.

Compares fullscan-image vs specials_x20 *after the same step-5 preprocessing*,
to decide whether specials_x20 is usable as a sanity-check anchor for the
conventional Hough branch.

Batch preprocessing (module.pipeline.preprocess) is called directly.
The visual-review server is NOT used, so reported statistics match exactly
what the batch pipeline sees.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from module.reader import load_spng                       # noqa: E402
from module.pipeline.finder import preprocess, _ZPJ_HALF  # noqa: E402
from module.pipeline import projection             # noqa: E402

# Step-5 params (config/default.yaml defaults; noise_amax_upper disabled)
FOG_KSIZE = 51
NOISE_AMIN = 2
NOISE_AMAX = 100
NOISE_CMP = 50
NOISE_AMAX_UPPER = 0

OUT_DIR = ROOT / "results" / "step5_compat"

FS_JSON = (
  "/gpfs/group/had/sks/E07/tohoku/fullscan/MOD108/PL12/"
  "tohoku-v1/AREA00/IMAGE00_AREA00/"
  "V00001173_L0_VX0003_VY0026_0_058.json"
)
SOURCES = [
  ("fullscan_V00001173", FS_JSON),
  ("KISO", str(ROOT / "specials_x20" / "KISO" / "image.json")),
  ("T011", str(ROOT / "specials_x20" / "T011" / "image.json")),
]


def quantiles(arr: np.ndarray, qs=(0, 25, 50, 75, 90, 100)) -> str:
  if arr.size == 0:
    return "(none)"
  vals = np.percentile(arr, qs)
  return "  ".join(f"p{q}={v:.0f}" for q, v in zip(qs, vals))


def analyse(name: str, json_path: str) -> dict:
  reader = load_spng(json_path)
  n = len(reader)
  z = reader.z_positions()
  dz_um = float(np.median(np.diff(z))) * 1000.0 if n > 1 else float("nan")
  affine = reader.affine_p2s
  # affine_p2s is a flat [a,b,c,d,e,f]; a is the x pixel->stage scale.
  # Fullscan view JSON stores identity (a=1); its physical scale lives in
  # config (0.29 um/px). Specials store the physical scale directly.
  px_raw = float(abs(affine[0]))
  px_um = px_raw * 1000.0
  px_note = " (identity; physical 0.29 from config)" if px_raw == 1.0 else ""
  center = n // 2

  proj, lo, hi = projection(reader, center)
  binary = preprocess(
    proj,
    fog_ksize=FOG_KSIZE,
    noise_amin=NOISE_AMIN,
    noise_amax=NOISE_AMAX,
    noise_cmp=NOISE_CMP,
    noise_amax_upper=NOISE_AMAX_UPPER,
  )
  fg_frac = float((binary > 0).mean())

  contours, _ = cv2.findContours(
    binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
  )
  areas = np.array([cv2.contourArea(c) for c in contours], dtype=np.float64)

  OUT_DIR.mkdir(parents=True, exist_ok=True)
  cv2.imwrite(str(OUT_DIR / f"{name}_proj.png"), proj)
  cv2.imwrite(str(OUT_DIR / f"{name}_binary.png"), binary)

  return {
    "name": name,
    "shape": proj.shape,
    "dtype": proj.dtype,
    "n_slices": n,
    "dz_um": dz_um,
    "px_um": px_um,
    "px_note": px_note,
    "center": center,
    "proj_window": (lo, hi),
    "raw_mean": float(proj.mean()),
    "raw_std": float(proj.std()),
    "raw_min": int(proj.min()),
    "raw_max": int(proj.max()),
    "fg_frac": fg_frac,
    "cc_count": int(areas.size),
    "cc_area_q": quantiles(areas),
  }


def main() -> None:
  print("Step-5 compatibility check "
        "(batch preprocess called directly; server NOT used)\n")
  print(f"Params: fog_ksize={FOG_KSIZE} noise_amin={NOISE_AMIN} "
        f"noise_amax={NOISE_AMAX} noise_cmp={NOISE_CMP} "
        f"noise_amax_upper={NOISE_AMAX_UPPER} zpj_half={_ZPJ_HALF}\n")
  rows = [analyse(name, jp) for name, jp in SOURCES]
  for r in rows:
    print(f"=== {r['name']} ===")
    print(f"  shape={r['shape']} dtype={r['dtype']} "
          f"n_slices={r['n_slices']} dz={r['dz_um']:.2f}um "
          f"px={r['px_um']:.4f}um{r['px_note']}")
    print(f"  center_slice={r['center']} "
          f"proj_window={r['proj_window']}")
    print(f"  raw proj: mean={r['raw_mean']:.1f} std={r['raw_std']:.1f} "
          f"min={r['raw_min']} max={r['raw_max']}")
    print(f"  post-step5 foreground fraction: {r['fg_frac']*100:.3f}%")
    print(f"  connected components: {r['cc_count']}")
    print(f"  CC area px^2: {r['cc_area_q']}")
    print()
  print(f"Saved projection + binary images to {OUT_DIR}/")


if __name__ == "__main__":
  main()
