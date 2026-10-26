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
            and the share held by the single best polyline (rec_best,
            the track found as one piece)
  polylines the fraction of a polyline's samples near some track grain
            (purity; under FAKE_PURITY is fake: count and total length)
            and the share of its matched samples on its main track
            (main_frac; low means it joins tracks)
  memory    peak RSS of the whole process tree (stage-1 workers summed)

One variant per process, so the peak RSS belongs to that variant.

  python scripts/graphdet_pointcloud.py EVENT_DIR --variant dog3d \
    [--dog-k 2] [--out results/pointcloud_eval/graphdet]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import replace
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
PIXEL_UM = 0.29        # the graph detector's MATLAB pixel size
RSS_POLL_S = 0.5


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


class TreeRSS:
  """Peak resident memory of this process and all its descendants,
  summed, sampled every RSS_POLL_S from /proc."""

  def __init__(self):
    self.peak_mb = 0.0
    self._stop = threading.Event()
    self._t = threading.Thread(target=self._run, daemon=True)

  @staticmethod
  def _tree_kb(root):
    kids, rss = {}, {}
    for d in os.listdir("/proc"):
      if not d.isdigit():
        continue
      try:
        with open(f"/proc/{d}/status") as f:
          st = dict(line.split(":", 1) for line in f if ":" in line)
      except OSError:
        continue
      kids.setdefault(int(st["PPid"]), []).append(int(d))
      rss[int(d)] = int(st.get("VmRSS", "0 kB").split()[0])
    total, todo = 0, [root]
    while todo:
      p = todo.pop()
      total += rss.get(p, 0)
      todo += kids.get(p, [])
    return total

  def _run(self):
    while not self._stop.is_set():
      self.peak_mb = max(self.peak_mb,
                         self._tree_kb(os.getpid()) / KB_PER_MB)
      self._stop.wait(RSS_POLL_S)

  def __enter__(self):
    self._t.start()
    return self

  def __exit__(self, *exc):
    self._stop.set()
    self._t.join()


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


def track_scores(g, shape, n_slices, polys, z_scale):
  """Per-track table and per-polyline table against grain truth."""
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
  # Per track: grain count, covered count, best single polyline
  tid, ti = np.unique(inst, return_inverse=True)
  n_g = np.bincount(ti)
  t_cls = np.zeros(len(tid), int)
  t_cls[ti] = cls
  cv = pid >= 0
  n_cov = np.bincount(ti[cv], minlength=len(tid))
  pair, c = np.unique(np.column_stack([ti[cv], pid[cv]]), axis=0,
                      return_counts=True)
  best = np.zeros(len(tid), int)
  np.maximum.at(best, pair[:, 0], c)
  n_poly = np.bincount(pair[:, 0], minlength=len(tid),
                       weights=c >= MIN_SHARE * n_cov[pair[:, 0]])
  keep = n_g >= MIN_TRACK_GRAINS
  tt = pd.DataFrame({"inst": tid, "cls": t_cls, "n_grains": n_g,
                     "rec_frac": n_cov / n_g, "rec_best": best / n_g,
                     "n_poly": n_poly.astype(int)})[keep]
  tt = tt.reset_index(drop=True)
  # Each polyline sample -> track of its nearest grain (or none).
  # Instance ids can be negative, so 'none' is kept as a mask.
  back = near(sp[:, :2], sp[:, 2], gxy, gz)
  owned = back >= 0
  n_p = len(polys)
  n_s = np.bincount(sid, minlength=n_p)
  n_on = np.bincount(sid[owned], minlength=n_p)
  pair, c = np.unique(np.column_stack([sid[owned],
                                       ti[back[owned]]]), axis=0,
                      return_counts=True)
  main = np.zeros(n_p, int)
  np.maximum.at(main, pair[:, 0], c)
  length = np.array([np.linalg.norm(np.diff(p, axis=0) * np.array(
    [1.0, 1.0, z_scale]), axis=1).sum() for p in polys])
  prow = {"poly": np.arange(n_p), "length_px": length,
          "purity": n_on / np.maximum(n_s, 1),
          "main_frac": main / np.maximum(n_on, 1)}
  return tt, pd.DataFrame(prow)


def quality(tt, pt):
  """Summary of the per-track and per-polyline tables."""
  fake = pt.purity < FAKE_PURITY if len(pt) else np.zeros(0, bool)
  row = {"n_fake": int(fake.sum()),
         "fake_frac": float(fake.mean()) if len(pt) else np.nan,
         "fake_len_px": float(pt.length_px[fake].sum()) if len(pt) else 0.,
         "main_frac_med": float(pt.main_frac[~fake].median())
         if (~fake).any() else np.nan}
  for nm, sub in (("bg", tt[tt.cls == 4]), ("sig", tt[tt.cls < 4])):
    if len(sub):
      row[f"{nm}_tracks"] = len(sub)
      row[f"{nm}_rec_mean"] = float(sub.rec_frac.mean())
      row[f"{nm}_good"] = float((sub.rec_frac >= REC_GOOD).mean())
      row[f"{nm}_best_mean"] = float(sub.rec_best.mean())
      row[f"{nm}_best_good"] = float((sub.rec_best >= REC_GOOD).mean())
      row[f"{nm}_npoly_med"] = float(sub.n_poly[sub.n_poly > 0].median())
  return row


def load_polys(path):
  """Polylines saved by main() (_polys.npz)."""
  z = np.load(path)
  return np.split(z["xyz"], np.cumsum(z["n"])[:-1]) if len(z["n"]) else []


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("event", type=Path)
  ap.add_argument("--variant", default="dog3d")
  ap.add_argument("--dog-k", type=float, default=ep.DOG_K)
  ap.add_argument("--workers", type=int, default=WORKERS)
  ap.add_argument("--z-um", type=float, default=None,
                  help="slice step (um) for the detector's z scale; "
                  "default keeps MATLAB_Z_SCALE (3.0 um)")
  ap.add_argument("--out", type=Path,
                  default=Path("results/pointcloud_eval/graphdet"))
  args = ap.parse_args()
  ev = args.event
  tag = args.variant if args.variant == PRODUCTION else \
    f"{args.variant}_k{args.dog_k:g}"
  if args.z_um is not None:
    tag += f"_z{args.z_um:g}"
  name = f"{ev.parent.name}__{ev.name}__{tag}"
  args.out.mkdir(parents=True, exist_ok=True)

  cfg = MATLAB_CONFIG.for_spacing(float(_GRAPH_CELL_PX))
  if args.z_um is not None:
    cfg = replace(cfg, z_scale=args.z_um / PIXEL_UM)
  with TreeRSS() as mem:
    t0 = time.time()
    x = hits_for(ev, args.variant, args.dog_k)
    t1 = time.time()
    n_reg = np.array([r[2].shape[0] for r in iter_regions(x)],
                     dtype=float)
    seg, _ = detect_lseg_view(x, cfg=cfg, workers=args.workers)
    t2 = time.time()
    polys = integrate_smallregions(x, seg, cfg)
    t3 = time.time()

  reader = load_spng(ev / "image.json")
  g = dict(np.load(ev / "grains.npz"))
  tt, pt = track_scores(g, reader.read(0).shape[:2], len(reader),
                        polys, cfg.z_scale)
  row = {"event": ev.name, "variant": tag, "n_hits": len(x),
         "region_max": int(n_reg.max()), "sum_n2": float((n_reg ** 2).sum()),
         "hits_s": round(t1 - t0, 1), "stage1_s": round(t2 - t1, 1),
         "stage2_s": round(t3 - t2, 1),
         "total_s": round(t3 - t0, 1),
         "rss_tree_peak_mb": round(mem.peak_mb),
         "n_segments": int(seg.shape[2]), "n_polylines": len(polys)}
  row.update(quality(tt, pt))
  tt.insert(0, "variant", tag)
  tt.insert(0, "event", ev.name)
  tt.to_csv(args.out / f"{name}_tracks.csv", index=False)
  # Polylines (export coordinates) for re-scoring without a rerun
  np.savez_compressed(args.out / f"{name}_polys.npz",
                      xyz=np.vstack(polys) if polys else np.zeros((0, 3)),
                      n=np.array([len(p) for p in polys], dtype=int))
  (args.out / f"{name}.json").write_text(json.dumps(row, indent=2))
  print(json.dumps(row), flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
