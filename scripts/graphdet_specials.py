"""Run the graph detector on a specials event and rank the true vertex.

The counterpart to scripts/rank_specials.py, which asks the same
question of the classical pipeline: for a confirmed reaction vertex,
where does it sit in the candidate list? Recall was never the problem
-- tests/test_specials.py finds every one of these events -- so the
comparison that decides whether the graph detector is worth its ~3
hours per view is the rank, not the hit.

Two things about specials stacks force choices here. They are up to
200 slices deep while graphdet's sub-regions are 80 (REGION_Z) and
silently drop anything past that, so the stack is windowed around the
true vertex's slice; the classical side must be given the same window
for the comparison to mean anything. And they are dense, so the export
uses the classifier denoise mode and a 6 px grid -- the configuration
the 2026-09-08 measurements settled on.

  python scripts/graphdet_specials.py --event D005 [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.graphdet import (
  MATLAB_CONFIG, attachment_codes, branch_points, detect_branches,
  detect_lseg_view, integrate_smallregions,
)
from module.graphdet.geom import scale_z
from module.matlab_export import export_hits_grid, _GRAPH_CELL_PX
from module.reader import load_spng
from module.track_classifier import build_training_set, train_classifier

_SPECIALS = Path(__file__).resolve().parents[2] / "specials_x20"
_GT_PATH = Path(__file__).resolve().parents[1] / "tests" / "specials_gt.json"
_LABELS = Path(__file__).resolve().parents[1] / "results" / "manual_labels"
# graphdet's sub-region depth; the window has to fit inside it.
_Z_WINDOW = 80
# Match radius for calling a reconstructed branch point the true one.
# The truth itself is only good to 200 px XY (expert click session), so
# a tighter radius would be measuring the clicks, not the detector.
_MATCH_PX = 200.0


def z_window(n_slices: int, centre: int) -> tuple[int, int]:
  """An 80-slice window around the true vertex, clipped to the stack."""
  lo = max(0, min(centre - _Z_WINDOW // 2, n_slices - _Z_WINDOW))
  return max(lo, 0), min(lo + _Z_WINDOW, n_slices)


def run(event: str, specials: Path, out_dir: Path) -> dict:
  gt_all = json.loads(_GT_PATH.read_text())
  gt = gt_all["events"][event]
  path = specials / event / "image.json"
  n_slices = len(load_spng(path))
  lo, hi = z_window(n_slices, int(gt["z_slice"]))

  t0 = time.time()
  clf = train_classifier(*build_training_set(_LABELS))
  method = "classifier" if clf is not None else "legacy"
  pl = export_hits_grid(path, cell=_GRAPH_CELL_PX, denoise_method=method,
                        classifier=clf, z_range=(lo, hi))
  t1 = time.time()
  print(f"{event}: slices {lo}-{hi} of {n_slices}, {pl.shape[0]} hits "
        f"({method}) in {t1 - t0:.0f} s", flush=True)

  x = pl[:, :3]
  cfg = MATLAB_CONFIG.for_spacing(float(_GRAPH_CELL_PX))
  seg, _ = detect_lseg_view(x, cfg=cfg)
  t2 = time.time()
  print(f"  stage 1: {seg.shape[2]} segments in {t2 - t1:.0f} s", flush=True)
  polys = integrate_smallregions(x, seg, cfg)
  t3 = time.time()
  print(f"  stage 2: {len(polys)} polylines in {t3 - t2:.0f} s", flush=True)
  codes = attachment_codes(polys, x, cfg)
  _, ids = detect_branches(polys, x, codes, cfg)
  pts, mult = branch_points(polys, x, codes, cfg)
  print(f"  stage 3: {len(pts)} branch points in {time.time() - t3:.0f} s",
        flush=True)

  res = {"event": event, "z_lo": lo, "z_hi": hi, "n_hits": int(x.shape[0]),
         "n_segments": int(seg.shape[2]), "n_polylines": len(polys),
         "n_branch_points": int(len(pts)), "denoise": method,
         "rank": None, "mult": None, "dist_px": None,
         "seconds": round(time.time() - t0, 1)}
  if len(pts):
    # Rank by multiplicity, the way a human would triage the list.
    order = np.argsort(-mult, kind="stable")
    p, m = pts[order], mult[order]
    d = np.linalg.norm(p[:, :2] - np.array([gt["vx"], gt["vy"]]), axis=1)
    res["dist_px"] = float(d.min())
    hit = np.flatnonzero(d <= _MATCH_PX)
    if hit.size:
      res["rank"] = int(hit[0]) + 1
      res["mult"] = int(m[hit[0]])
  out_dir.mkdir(parents=True, exist_ok=True)
  (out_dir / f"{event}.json").write_text(json.dumps(res, indent=2))
  print(f"  -> rank {res['rank']} of {res['n_branch_points']}, "
        f"mult {res['mult']}, nearest {res['dist_px']} px", flush=True)
  return res


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--event", required=True)
  ap.add_argument("--specials", type=Path, default=_SPECIALS)
  ap.add_argument("--out", type=Path,
                  default=Path("results/graphdet_specials"))
  args = ap.parse_args()
  run(args.event, args.specials, args.out)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
