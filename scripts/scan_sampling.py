"""How the graph detector degrades as the hits get sparser.

The simulation the MATLAB constants were tuned on samples a track
every ~3 px (``mabiki(pl, 3)``). The real E07 export samples every
30 px (``matlab_export._GRID_CELL_PX``), so the detector runs on data
ten times sparser than anything it was tuned for -- and distance
constants like the 20 px endpoint-growth window then span less than
one gap between hits.

This re-thins the SAME simulation at other block sizes, which keeps
the truth intact, and measures efficiency and purity at each. It says
which block sizes still work and therefore what has to change before
the detector is pointed at E07 data.

With --scale-constants the length-scale constants are rescaled to the
block size (DetectorConfig.for_spacing), which is the fix this
measurement exists to test.

  python scripts/scan_sampling.py [--events 1-3] [--blocks 3,6,10,30]
                                  [--scale-constants]
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import scipy.io as sio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.graphdet import (
  MATLAB_CONFIG, MATLAB_Z_SCALE, mabiki, run_pipeline, score,
  true_branch_points,
)

_DEFAULT_MAT = Path(__file__).parents[2] / "matlab" / "simdata8.mat"
_DEFAULT_BLOCKS = "3,6,10,15,20,30"
_MATCH_PX = 25.0
_E07_EXPORT_BLOCK_PX = 30


def parse_ints(spec: str) -> list[int]:
  out: list[int] = []
  for part in spec.split(","):
    if "-" in part:
      lo, hi = part.split("-")
      out.extend(range(int(lo), int(hi) + 1))
    else:
      out.append(int(part))
  return out


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--mat", type=Path, default=_DEFAULT_MAT)
  ap.add_argument("--events", default="1-3")
  ap.add_argument("--blocks", default=_DEFAULT_BLOCKS)
  ap.add_argument("--z-scale", type=float, default=MATLAB_Z_SCALE,
                  help="isotropic scale for the slice axis")
  ap.add_argument("--match-px", type=float, default=_MATCH_PX)
  ap.add_argument("--scale-constants", action="store_true",
                  help="rescale length constants to the block size")
  args = ap.parse_args()

  data = sio.loadmat(args.mat)
  events = parse_ints(args.events)
  blocks = parse_ints(args.blocks)
  print(f"events {events}, match radius {args.match_px:.0f} px, "
        f"z_scale {args.z_scale:.3f}, "
        f"constants {'scaled to block' if args.scale_constants else 'MATLAB'}")
  print(f"(the E07 export samples at {_E07_EXPORT_BLOCK_PX} px)\n")
  print("block   hits   spacing   segments  tracks  vertices   "
        "efficiency   purity    time")

  for block in blocks:
    totals = {"n_truth": 0, "n_found": 0, "matched_truth": 0,
              "matched_found": 0, "merged": 0}
    n_hits = n_seg = n_poly = 0
    t0 = time.time()
    for event in events:
      pl = np.asarray(data["pl"].ravel()[event - 1], dtype=float)
      summary = np.asarray(
        data["Summary"].ravel()[event - 1], dtype=float)
      hits = mabiki(pl[:, :3], block)[:, :3]
      truth, _ = true_branch_points(summary)
      cfg = replace(MATLAB_CONFIG, z_scale=args.z_scale)
      if args.scale_constants:
        cfg = cfg.for_spacing(float(block))
      out = run_pipeline(hits, cfg)
      s = score(truth, out["points"], args.match_px, args.z_scale)
      for k in totals:
        totals[k] += s[k]
      n_hits += hits.shape[0]
      n_seg += out["segments"].shape[2]
      n_poly += len(out["polylines"])
    eff = totals["matched_truth"] / max(1, totals["n_truth"])
    pur = totals["matched_found"] / max(1, totals["n_found"])
    print(f"{block:5d} {n_hits:7d} {block:7d}px {n_seg:9d} {n_poly:7d} "
          f"{totals['n_found']:9d}   "
          f"{eff:6.1%} ({totals['matched_truth']:3d}/{totals['n_truth']})"
          f"  {pur:6.1%}  {time.time() - t0:6.1f}s")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
