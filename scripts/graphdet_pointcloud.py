"""Graph detector stages 1-2 on one point cloud of a synthetic event.

The point-cloud harness (scripts/eval_pointcloud.py) scores hits
against grain truth, but what the export feeds is the graph detector,
and its cost grows as the square of the hits in a sub-region. This runs
detect_lseg_view and integrate_smallregions on one variant's hits and
records what the downstream sees:

  cost      stage 1 / 2 wall time, peak RSS (this process and its
            stage-1 workers), sum over sub-regions of N^2, max N,
            segment and polyline counts
  tracks    per true track (classes 1-4, >= MIN_TRACK_GRAINS grains in
            view): the fraction of its grains within COVER_R_PX (box)
            and Z_TOL_SLICES of a polyline sample (rec_frac), and how many
            polylines share those grains (n_poly, counting a polyline
            once it holds MIN_SHARE of them)
  polylines the fraction of a polyline's samples near some track grain
            (purity); one under FAKE_PURITY is called fake

One variant per process, so the peak RSS belongs to that variant.

  python scripts/graphdet_pointcloud.py EVENT_DIR --variant dog3d \
    [--dog-k 2] [--out results/pointcloud_eval/graphdet]
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_pointcloud as ep                                  # noqa: E402
from module.graphdet import MATLAB_CONFIG, integrate_smallregions  # noqa
from module.graphdet.detectlseg import (                      # noqa: E402
  detect_lseg_view, iter_regions,
)
from module.matlab_export import (                            # noqa: E402
  _GRAPH_CELL_PX, _ORIGIN_OFFSET, export_hits_grid,
)
from module.reader import load_spng                           # noqa: E402
from module.track_classifier import (                         # noqa: E402
  build_training_set, train_classifier,
)

WORKERS = 8
COVER_R_PX = ep.COVER_R_PX
Z_TOL_SLICES = ep.Z_TOL_SLICES
MIN_TRACK_GRAINS = ep.MIN_TRACK_GRAINS
# Polyline sampling step (px, slices counted as px)
SAMPLE_STEP_PX = 1.0
# A polyline counts towards a track's fragments once it holds this
# fraction of the track's covered grains.
MIN_SHARE = 0.1
FAKE_PURITY = 0.3
REC_GOOD = 0.5
KB_PER_MB = 1024.0
PRODUCTION = "production"


def hits_for(ev, variant, dog_k):
  """(N, 3) hits in export coordinates (1-based x, y and slice)."""
  path = ev / "image.json"
  if variant == PRODUCTION:
    clf = train_classifier(*build_training_set(ep._LABELS_DIR))
    pl = export_hits_grid(path, cell=_GRAPH_CELL_PX,
                          denoise_method="classifier", classifier=clf)
    return pl[:, :3].astype(float)
  ep.DOG_K = dog_k
  hits, _ = ep.build_hits(load_spng(path), (variant,), None,
                          _GRAPH_CELL_PX)
  return hits[variant][:, :3] + _ORIGIN_OFFSET


def sample(polys):
  """Points every SAMPLE_STEP_PX along each polyline, with its index."""
  pts, ids = [], []
  for i, p in enumerate(polys):
    for a, b in zip(p[:-1], p[1:]):
      n = max(int(np.ceil(np.linalg.norm(b - a) / SAMPLE_STEP_PX)), 1)
      t = np.linspace(0.0, 1.0, n + 1)[:, None]
      pts.append(a + t * (b - a))
      ids.append(np.full(n + 1, i))
  if not pts:
    return np.zeros((0, 3)), np.zeros(0, int)
  return np.vstack(pts), np.concatenate(ids)


def near(a_xy, a_z, b_xy, b_z):
  """For each a, the index of the nearest b inside the box COVER_R_PX
  in x and y and Z_TOL_SLICES + 0.5 in z (Chebyshev metric with z
  rescaled to the box), or -1."""
  if not len(b_xy):
    return np.full(len(a_xy), -1)
  zs = COVER_R_PX / (Z_TOL_SLICES + 0.5)
  tree = cKDTree(np.column_stack([b_xy, b_z * zs]))
  d, j = tree.query(np.column_stack([a_xy, a_z * zs]), p=np.inf,
                    distance_upper_bound=COVER_R_PX + 1e-9)
  return np.where(np.isfinite(d), j, -1)


def track_scores(g, shape, n_slices, polys):
  """Per-track table and polyline purities against grain truth."""
  h, w = shape
  vis = ((g["cls"] >= 1) & (g["cls"] <= 4) & ~g["fog"]
         & (g["col"] >= 0) & (g["col"] < w) & (g["row"] >= 0)
         & (g["row"] < h) & (g["slice"] >= 0) & (g["slice"] < n_slices))
  gxy = np.column_stack([g["col"], g["row"]])[vis]
  gz = g["slice"][vis]
  inst, cls = g["instance"][vis], g["cls"][vis]
  sp, sid = sample(polys)
  sp = sp - _ORIGIN_OFFSET
  hit = near(gxy, gz, sp[:, :2], sp[:, 2])
  pid = np.where(hit >= 0, sid[np.maximum(hit, 0)], -1)
  rows = []
  for t in np.unique(inst):
    m = inst == t
    if m.sum() < MIN_TRACK_GRAINS:
      continue
    p = pid[m]
    cov = p[p >= 0]
    n_poly = 0
    if cov.size:
      _, c = np.unique(cov, return_counts=True)
      n_poly = int((c >= MIN_SHARE * cov.size).sum())
    rows.append({"inst": int(t), "cls": int(cls[m][0]),
                 "n_grains": int(m.sum()),
                 "rec_frac": float(cov.size / m.sum()),
                 "n_poly": n_poly})
  tt = pd.DataFrame(rows)
  back = near(sp[:, :2], sp[:, 2], gxy, gz) >= 0
  purity = (pd.Series(back).groupby(sid).mean().to_numpy()
            if len(sid) else np.zeros(0))
  return tt, purity


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("event", type=Path)
  ap.add_argument("--variant", default="dog3d")
  ap.add_argument("--dog-k", type=float, default=ep.DOG_K)
  ap.add_argument("--workers", type=int, default=WORKERS)
  ap.add_argument("--out", type=Path,
                  default=Path("results/pointcloud_eval/graphdet"))
  args = ap.parse_args()
  ev = args.event
  tag = args.variant if args.variant == PRODUCTION else \
    f"{args.variant}_k{args.dog_k:g}"
  name = f"{ev.parent.name}__{ev.name}__{tag}"
  args.out.mkdir(parents=True, exist_ok=True)

  t0 = time.time()
  x = hits_for(ev, args.variant, args.dog_k)
  t1 = time.time()
  n_reg = np.array([r[2].shape[0] for r in iter_regions(x)], dtype=float)
  cfg = MATLAB_CONFIG.for_spacing(float(_GRAPH_CELL_PX))
  seg, _ = detect_lseg_view(x, cfg=cfg, workers=args.workers)
  t2 = time.time()
  polys = integrate_smallregions(x, seg, cfg)
  t3 = time.time()
  rss = {who: resource.getrusage(w).ru_maxrss / KB_PER_MB for who, w in
         (("self", resource.RUSAGE_SELF),
          ("workers", resource.RUSAGE_CHILDREN))}

  reader = load_spng(ev / "image.json")
  g = dict(np.load(ev / "grains.npz"))
  tt, purity = track_scores(g, reader.read(0).shape[:2], len(reader),
                            polys)
  row = {"event": ev.name, "variant": tag, "n_hits": len(x),
         "region_max": int(n_reg.max()), "sum_n2": float((n_reg ** 2).sum()),
         "hits_s": round(t1 - t0, 1), "stage1_s": round(t2 - t1, 1),
         "stage2_s": round(t3 - t2, 1),
         "rss_self_mb": round(rss["self"]), "rss_worker_mb":
         round(rss["workers"]), "n_segments": int(seg.shape[2]),
         "n_polylines": len(polys),
         "fake_frac": float((purity < FAKE_PURITY).mean())
         if len(purity) else np.nan}
  for nm, sub in (("bg", tt[tt.cls == 4]), ("sig", tt[tt.cls < 4])):
    if len(sub):
      row[f"{nm}_tracks"] = len(sub)
      row[f"{nm}_rec_mean"] = float(sub.rec_frac.mean())
      row[f"{nm}_good"] = float((sub.rec_frac >= REC_GOOD).mean())
      row[f"{nm}_npoly_med"] = float(sub.n_poly[sub.n_poly > 0].median())
  tt.insert(0, "variant", tag)
  tt.insert(0, "event", ev.name)
  tt.to_csv(args.out / f"{name}_tracks.csv", index=False)
  (args.out / f"{name}.json").write_text(json.dumps(row, indent=2))
  print(json.dumps(row), flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
