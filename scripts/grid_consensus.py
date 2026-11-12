"""Grid-shift consensus for B' polylines, scored on synthetic truth.

Stage 1 of the graph detector cuts the view into 128 px sub-regions, and
about half of its output changes when that grid moves by 64 px with the
very same hits (segment_repro.py gridshift). Lines that survive a moved
grid are less likely to be artefacts of the cut. This reruns stages 1
and 2 with the grid at GRID_SHIFTS_PX (17 x 17 regions, so no hit falls
off the grid), keeps each base-run polyline that >= M shifted runs
reproduce (>= OWN_REPRO of its length within CONS_R_PX, MATCH_DZ_UM and
MATCH_DEG; segment_repro.best_match) and compares all / kept / a random
subset of the kept size:

  tracks    graphdet_pointcloud.track_scores / quality (signal and
            background recovery, best single polyline >= 50 %)
  vertices  stage-3 branch points and, per in-view truth vertex, the
            distance to the nearest one, and the best darkness rank
            (module.pipeline.union, production keeps the top TOP_K)
            among those within CAPTURE_UM; chance_12um is the count a
            random spot would expect

  python scripts/grid_consensus.py DATASET_DIR [--events ev0100 ...] \
    [--out results/grid_consensus]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import graphdet_pointcloud as gp                              # noqa: E402
from segment_repro import best_match, sample                  # noqa: E402
from module.graphdet import (                                 # noqa: E402
  MATLAB_CONFIG, attachment_codes, branch_points, integrate_smallregions,
)
from module.graphdet.detectlseg import N_REGIONS, detect_lseg_view  # noqa
from module.matlab_export import _GRAPH_CELL_PX, _ORIGIN_OFFSET  # noqa
from module.pipeline.union import TOP_K, local_darkness, top_k  # noqa
from module.reader import load_spng                           # noqa: E402

GRID_SHIFTS_PX = ((0, 0), (64, 0), (0, 64), (64, 64))
N_REGIONS_SHIFTED = N_REGIONS + 1
DETECTOR_Z_UM = 3.8     # production z scale of the v20 tune runs
# Pixel size and slice step of the event, from truth.json (pixel_um,
# physical_dz_um); these defaults are v20's, which records neither.
SIM_PX_UM = 0.289
SIM_SLICE_UM = 4.0
CONS_R_PX = 4.0
MATCH_DZ_UM = 15.0
OWN_REPRO = 0.5
MIN_RUNS = (1, 2, 3)
CAPTURE_UM = 12.0
WORKERS = 12
RAND_SEED = 1
OUT = Path("results/grid_consensus")


def run_shift(x, shift, cfg, f):
  """Polylines of stages 1-2 with the grid moved by shift (px), back in
  the hits' coordinates; cached in f."""
  if f.exists():
    return gp.load_polys(f)
  sh = np.array([shift[0], shift[1], 0.0])
  n_reg = N_REGIONS if not any(shift) else N_REGIONS_SHIFTED
  seg, _ = detect_lseg_view(x + sh, cfg=cfg, workers=WORKERS,
                            n_regions=n_reg)
  polys = [q - sh for q in integrate_smallregions(x + sh, seg, cfg)]
  np.savez_compressed(f, xyz=np.vstack(polys) if polys
                      else np.zeros((0, 3)),
                      n=np.array([len(p) for p in polys], dtype=int))
  return polys


def as_src(s):
  """segment_repro samples -> (xy px, z um, unit direction)."""
  return s[:, :2], s[:, 2] * SIM_SLICE_UM, s[:, 3:5]


def n_reproduced(base, others):
  """Per base polyline, how many of the other runs reproduce >=
  OWN_REPRO of its length."""
  s = sample(base)
  owner, w = s[:, 5].astype(int), s[:, 6]
  tot = np.bincount(owner, weights=w, minlength=len(base))
  src = as_src(s)
  count = np.zeros(len(base), int)
  for polys in others:
    so = as_src(sample(polys))
    d, _ = best_match(src, (cKDTree(so[0]), so[1], so[2]), CONS_R_PX,
                      MATCH_DZ_UM)
    rep = np.bincount(owner, weights=w * (d <= CONS_R_PX),
                      minlength=len(base))
    count += rep >= OWN_REPRO * np.maximum(tot, 1e-9)
  return count, tot * SIM_PX_UM


def vertex_dist(pts, truth, rank):
  """Per in-view truth vertex: distance (um) to the nearest branch point
  (export coordinates, inf if none) and the best darkness rank (1 =
  darkest) among the branch points within CAPTURE_UM (0 if none)."""
  v = [t for t in truth["vertices"] if t["in_view"]]
  if not v or not len(pts):
    return [np.inf] * len(v), [0] * len(v), [t["type"] for t in v]
  scale = np.array([SIM_PX_UM, SIM_PX_UM, SIM_SLICE_UM])
  tv = np.array([[t["col"], t["row"], t["slice"]] for t in v]) * scale
  tree = cKDTree((pts - _ORIGIN_OFFSET) * scale)
  d, _ = tree.query(tv)
  best = [int(rank[j].min()) + 1 if j else 0
          for j in tree.query_ball_point(tv, CAPTURE_UM)]
  return list(d), best, [t["type"] for t in v]


def chance(n_pts, shape, n_slices):
  """Expected branch points within CAPTURE_UM of a random spot."""
  vol = (shape[0] * shape[1] * SIM_PX_UM ** 2) * n_slices * SIM_SLICE_UM
  return n_pts * 4.0 / 3.0 * np.pi * CAPTURE_UM ** 3 / vol


def score_event(ev, out, detector_px_um):
  global SIM_PX_UM, SIM_SLICE_UM
  truth = json.loads((ev / "truth.json").read_text())
  SIM_PX_UM = truth.get("pixel_um", SIM_PX_UM)
  SIM_SLICE_UM = truth.get("physical_dz_um", SIM_SLICE_UM)
  cfg = replace(MATLAB_CONFIG.for_spacing(float(_GRAPH_CELL_PX)),
                z_scale=DETECTOR_Z_UM / detector_px_um)
  fh = out / f"{ev.name}_hits.npz"
  if fh.exists():
    x = np.load(fh)["hits"]
  else:
    x = gp.hits_for(ev, gp.PRODUCTION, None)
    np.savez_compressed(fh, hits=x)
  runs = [run_shift(x, s, cfg, out / f"{ev.name}_s{s[0]}_{s[1]}.npz")
          for s in GRID_SHIFTS_PX]
  base = runs[0]
  n_rep, length = n_reproduced(base, runs[1:])
  pd.DataFrame({"length_um": length, "n_repro": n_rep}).to_csv(
    out / f"{ev.name}_polylines.csv", index=False)
  rng = np.random.default_rng(RAND_SEED)
  sets = {"all": np.ones(len(base), bool)}
  for m in MIN_RUNS:
    sets[f"keep{m}"] = n_rep >= m
  rand = np.zeros(len(base), bool)
  rand[rng.choice(len(base), sets["keep1"].sum(), replace=False)] = True
  sets["random1"] = rand
  reader = load_spng(ev / "image.json")
  g = dict(np.load(ev / "grains.npz"))
  stack = reader.read_stack()
  shape = stack.shape[1:]
  rows = []
  for tag, sel in sets.items():
    polys = [p for p, k in zip(base, sel) if k]
    tt, pt = gp.track_scores(g, reader.read(0).shape[:2], len(reader),
                             polys, cfg.z_scale)
    pts, _ = branch_points(polys, x, attachment_codes(polys, x, cfg), cfg)
    dark = local_darkness(stack, pts[:, :2] - _ORIGIN_OFFSET,
                          pts[:, 2] - _ORIGIN_OFFSET)
    rank = np.empty(len(pts), int)
    rank[top_k(dark, len(pts))] = np.arange(len(pts))
    np.savez_compressed(out / f"{ev.name}_{tag}_branch.npz", pts=pts,
                        dark=dark)
    d, best, types = vertex_dist(pts, truth, rank)
    row = {"event": ev.name, "set": tag, "n_polylines": len(polys),
           "length_mm": float(length[sel].sum() / 1e3),
           "n_branch": len(pts),
           "chance_12um": float(chance(len(pts), shape, len(reader)))}
    row.update(gp.quality(tt, pt))
    sig = tt[tt.cls < 4]
    row["sig_short_best_good"] = float(
      (sig.rec_best[sig.n_grains < gp.MIN_TRACK_GRAINS * 3]
       >= gp.REC_GOOD).mean()) if len(sig) else np.nan
    row["vtx_types"] = ";".join(types)
    row["vtx_dist_um"] = ";".join(f"{v:.1f}" for v in d)
    row["vtx_dark_rank"] = ";".join(map(str, best))
    row["capture_hit"] = bool(len(d) and d[0] <= CAPTURE_UM)
    row["capture_top_k"] = bool(len(best) and 0 < best[0] <= TOP_K)
    row["vtx_hit_frac"] = float(np.mean(np.array(d) <= CAPTURE_UM)) \
      if d else np.nan
    rows.append(row)
    print(json.dumps(row), flush=True)
  return rows


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("dataset", type=Path)
  ap.add_argument("--events", nargs="*", default=None)
  ap.add_argument("--out", type=Path, default=OUT)
  ap.add_argument("--detector-px-um", type=float, default=gp.PIXEL_UM,
                  help="pixel size in the detector's z scale (3.8 um "
                  "per slice over this); production 0.29, true 0.507")
  args = ap.parse_args()
  args.out.mkdir(parents=True, exist_ok=True)
  evs = sorted(p for p in args.dataset.glob("ev*") if p.is_dir())
  if args.events:
    evs = [e for e in evs if e.name in args.events]
  rows = []
  for ev in evs:
    rows += score_event(ev, args.out, args.detector_px_um)
    pd.DataFrame(rows).to_csv(args.out / "scores.csv", index=False)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
