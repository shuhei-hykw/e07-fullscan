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
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.graphdet import (
  E07_SLICE_UM, E07_Z_SCALE, MATLAB_CONFIG, attachment_codes, branch_points,
  detect_branches, detect_lseg_view, integrate_smallregions,
)
from module.graphdet.support import (
  sample, supported_pieces, unsupported_fraction,
)
from module.graphdet.geom import scale_z
from module.matlab_export import (
  export_hits_grid, _GRAPH_CELL_PX, _ORIGIN_OFFSET,
)
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
_UM_PER_MM = 1000.0
# Processes for stage 1 (the 256 sub-regions are independent)
_WORKERS = 12
# Hits per sub-region the detector is affordable at. Stage 1 costs
# roughly N^2 in the hits of one 128x128x80 region: ~40 s at 3,000 and
# over 32 minutes at 6,700, which is 140 h per view. specials events
# differ eightfold in density, so a fixed cell size cannot serve them
# all -- the cell is widened until a region holds about this many.
_TARGET_PER_REGION = 3500
_N_REGIONS = 256
_CELL_STEPS = (6, 8, 10, 12, 16, 20, 24, 30)
# Hit count against cell size, measured on a full-scan tile: 1,667,324
# at 6 px and 240,824 at 30 px, so hits ~ cell^-1.2. Used to jump
# straight to a workable cell instead of re-exporting at each step,
# since one export is ~20 minutes.
_HIT_DENSITY_EXPONENT = 1.2
_MAX_EXPORT_TRIES = 3
PRODUCTION = "production"
# Random positions (same depth as the truth) whose best candidate rank
# shows what a 200 px best-of-many match gives by chance.
_RAND_N = 1000
_RAND_SEED = 20261028
# Ranks reported as "found within the first K".
_TOP_K = (10, 100)
# A branch point this close (z-scaled px) to a salvage cut end is
# counted as possibly made by the cut.
_CUT_NEAR_PX = 5.0
# Polylines passing this close to the matched branch point (x/y px,
# slices) are its prongs; one slice is ~13 px once z is scaled.
_PRONG_XY_PX = 10.0
_PRONG_Z_SLICES = 2.0


class _Window:
  """The slices lo..hi-1 of a stack, as a reader."""

  def __init__(self, reader, lo: int, hi: int):
    self.reader, self.lo, self.hi = reader, lo, hi

  def __len__(self) -> int:
    return self.hi - self.lo

  def read(self, i: int) -> np.ndarray:
    return self.reader.read(self.lo + i)


def dog3dz_hits(path: Path, lo: int, hi: int, dog_k: float) -> np.ndarray:
  """3-D DoG hits (parabola z) of the window, in export coordinates."""
  sys.path.insert(0, str(Path(__file__).resolve().parent))
  import eval_pointcloud as ep
  ep.DOG_K = dog_k
  hits, _ = ep.build_hits(_Window(load_spng(path), lo, hi), ("dog3dz",),
                          None, _GRAPH_CELL_PX)
  return hits["dog3dz"][:, :3] + _ORIGIN_OFFSET


def rank_of(d_xy, dz_ok):
  """1-based rank of the first candidate within reach, or None."""
  hit = np.flatnonzero((d_xy <= _MATCH_PX) & dz_ok)
  return (int(hit[0]) + 1 if hit.size else None), int(hit.size)


def z_window(n_slices: int, centre: int) -> tuple[int, int]:
  """An 80-slice window around the true vertex, clipped to the stack."""
  lo = max(0, min(centre - _Z_WINDOW // 2, n_slices - _Z_WINDOW))
  return max(lo, 0), min(lo + _Z_WINDOW, n_slices)


def run(event: str, specials: Path, out_dir: Path,
        cell_min: int = _GRAPH_CELL_PX, fixed_cell: bool = False,
        workers: int = _WORKERS, variant: str = PRODUCTION,
        dog_k: float = 2.0, max_gap_frac: float | None = None,
        salvage: bool = False) -> dict:
  gt_all = json.loads(_GT_PATH.read_text())
  gt = gt_all["events"][event]
  path = specials / event / "image.json"
  n_slices = len(load_spng(path))
  lo, hi = z_window(n_slices, int(gt["z_slice"]))

  t0 = time.time()
  tag = PRODUCTION if variant == PRODUCTION else f"{variant}_k{dog_k:g}"
  if max_gap_frac is not None:
    tag += f"_g{max_gap_frac:g}" + ("s" if salvage else "")
  clf = train_classifier(*build_training_set(_LABELS)) \
    if variant == PRODUCTION else None
  method = variant if variant != PRODUCTION else \
    "classifier" if clf is not None else "legacy"
  cell = cell_min
  for attempt in range(_MAX_EXPORT_TRIES if variant == PRODUCTION else 0):
    pl = export_hits_grid(path, cell=cell, denoise_method=method,
                          classifier=clf, z_range=(lo, hi))
    per_region = pl.shape[0] / _N_REGIONS
    print(f"{event}: slices {lo}-{hi} of {n_slices}, cell {cell} px -> "
          f"{pl.shape[0]} hits ({per_region:.0f}/region)", flush=True)
    if fixed_cell or per_region <= _TARGET_PER_REGION:
      break
    want = cell * (per_region / _TARGET_PER_REGION) ** (
      1.0 / _HIT_DENSITY_EXPONENT)
    nxt = next((c for c in _CELL_STEPS if c >= want), _CELL_STEPS[-1])
    if nxt <= cell:
      break
    print(f"  too dense; retrying at {nxt} px", flush=True)
    cell = nxt
  t1 = time.time()
  print(f"  export ({method}) in {t1 - t0:.0f} s", flush=True)

  if variant == PRODUCTION:
    x = pl[:, :3]
  else:
    x = dog3dz_hits(path, lo, hi, dog_k)
    t1 = time.time()
    print(f"{event}: slices {lo}-{hi} of {n_slices}, {variant} -> "
          f"{len(x)} hits in {t1 - t0:.0f} s", flush=True)
  cfg = replace(MATLAB_CONFIG.for_spacing(float(cell)),
                z_scale=E07_Z_SCALE)
  seg, _ = detect_lseg_view(x, cfg=cfg, workers=workers)
  t2 = time.time()
  print(f"  stage 1: {seg.shape[2]} segments in {t2 - t1:.0f} s", flush=True)
  polys = integrate_smallregions(x, seg, cfg)
  parent = np.arange(len(polys))
  cut = np.zeros((len(polys), 2), bool)
  n_raw = len(polys)
  if max_gap_frac is not None:
    keep = unsupported_fraction(polys, x, cfg.z_scale) <= max_gap_frac
    kept = [p for p, k in zip(polys, keep) if k]
    parent, cut = parent[keep], cut[keep]
    if salvage:
      drop = np.flatnonzero(~keep)
      pc, pp, pcut = supported_pieces([polys[i] for i in drop], x,
                                      cfg.z_scale, with_parent=True)
      kept += pc
      parent = np.r_[parent, drop[pp]]
      cut = np.vstack([cut, pcut])
    polys = kept
  t3 = time.time()
  print(f"  stage 2: {n_raw} polylines, {len(polys)} after filter in "
        f"{t3 - t2:.0f} s", flush=True)
  codes = attachment_codes(polys, x, cfg)
  _, ids = detect_branches(polys, x, codes, cfg)
  pts, mult = branch_points(polys, x, codes, cfg)
  print(f"  stage 3: {len(pts)} branch points in {time.time() - t3:.0f} s",
        flush=True)

  res = {"event": event, "variant": tag, "cell_px": int(cell),
         "n_polylines_raw": n_raw, "n_pieces": int(cut.any(1).sum()),
         "length_px": float(sum(np.linalg.norm(np.diff(p, axis=0)
                                               * [1, 1, cfg.z_scale],
                                               axis=1).sum()
                                for p in polys)),
         "z_lo": lo, "z_hi": hi, "n_hits": int(x.shape[0]),
         "n_segments": int(seg.shape[2]), "n_polylines": len(polys),
         "n_branch_points": int(len(pts)), "denoise": method,
         "rank": None, "mult": None, "dist_px": None,
         "seconds": round(time.time() - t0, 1)}
  if len(pts):
    # Rank by multiplicity, the way a human would triage the list.
    order = np.argsort(-mult, kind="stable")
    p, m = pts[order], mult[order]
    # Back to image coordinates: the export adds a 1-based origin to
    # x, y and z, and z counts slices from the window's first slice.
    xy = p[:, :2] - _ORIGIN_OFFSET
    d = np.linalg.norm(xy - np.array([gt["vx"], gt["vy"]]), axis=1)
    res["dist_px"] = float(d.min())
    zs = load_spng(path).z_positions()
    sl = p[:, 2] - _ORIGIN_OFFSET + lo
    z_mm = np.interp(sl, np.arange(len(zs)), zs)
    z_true = zs[int(gt["z_slice"])]
    tol_um = gt_all.get("tolerance_z_um", 30)
    # Stage z (the old definition) and developed-emulsion depth (slice
    # difference times the slice step), both within tol_um
    ok_stage = np.abs(z_mm - z_true) <= tol_um / _UM_PER_MM
    ok_phys = np.abs(sl - gt["z_slice"]) * E07_SLICE_UM <= tol_um
    res["match"] = "xy+z_stage"
    res["rank"], res["n_match"] = rank_of(d, ok_stage)
    if res["rank"]:
      res["mult"] = int(m[res["rank"] - 1])
    res["rank_phys"], res["n_match_phys"] = rank_of(d, ok_phys)
    res["rank_frac_phys"] = res["rank_phys"] / len(p) \
      if res["rank_phys"] else None
    for k in _TOP_K:
      res[f"top{k}_phys"] = bool(res["rank_phys"]
                                 and res["rank_phys"] <= k)
    # Chance: the same match from random positions at the true depth
    h, w = load_spng(path).read(0).shape[:2]
    rng = np.random.default_rng(_RAND_SEED)
    rr = []
    for q in rng.uniform([0, 0], [w, h], size=(_RAND_N, 2)):
      r, _ = rank_of(np.linalg.norm(xy - q, axis=1), ok_phys)
      rr.append(r if r else len(p) + 1)
    rr = np.array(rr)
    res["rand_rank_med_phys"] = float(np.median(rr))
    if res["rank_phys"]:
      res["rand_le_rank_phys"] = float((rr <= res["rank_phys"]).mean())
      # Prongs: polylines passing near the matched branch point, and
      # how many different stage-2 polylines they came from
      b = p[res["rank_phys"] - 1]
      sp, sid = sample(polys, cfg.z_scale)
      near = np.unique(sid[(np.linalg.norm(sp[:, :2] - b[:2], axis=1)
                            <= _PRONG_XY_PX)
                           & (np.abs(sp[:, 2] - b[2]) <= _PRONG_Z_SLICES)])
      res["prongs"] = len(near)
      res["prong_parents"] = int(len(set(parent[near].tolist())))
  if len(pts) and cut.any():
    ends = np.array([q[[0, -1]] for q in polys])[cut.any(1)]
    ce = np.vstack([e[c] for e, c in zip(ends, cut[cut.any(1)])])
    dc, _ = cKDTree(ce * [1, 1, cfg.z_scale]).query(
      pts * [1, 1, cfg.z_scale])
    res["bp_near_cut"] = int((dc <= _CUT_NEAR_PX).sum())
  out_dir.mkdir(parents=True, exist_ok=True)
  name = event if variant == PRODUCTION and max_gap_frac is None \
    else f"{event}__{tag}"
  (out_dir / f"{name}.json").write_text(json.dumps(res, indent=2))
  np.savez_compressed(out_dir / f"{name}_polys.npz",
                      xyz=np.vstack(polys) if polys else np.zeros((0, 3)),
                      n=np.array([len(q) for q in polys]), parent=parent,
                      cut=cut, z_lo=lo)
  # Every branch point, so other rankings can be tried without a rerun.
  sl = pts[:, 2] - _ORIGIN_OFFSET + lo if len(pts) else np.zeros(0)
  zs = load_spng(path).z_positions()
  pd.DataFrame({
    "vx_px": pts[:, 0] - _ORIGIN_OFFSET if len(pts) else [],
    "vy_px": pts[:, 1] - _ORIGIN_OFFSET if len(pts) else [],
    "slice": sl, "z_mm": np.interp(sl, np.arange(len(zs)), zs),
    "mult": mult if len(pts) else [],
  }).to_csv(out_dir / f"{name}_points.csv", index=False)
  print(f"  -> rank {res['rank']} of {res['n_branch_points']}, "
        f"mult {res['mult']}, nearest {res['dist_px']} px", flush=True)
  return res


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--event", required=True)
  ap.add_argument("--specials", type=Path, default=_SPECIALS)
  ap.add_argument("--out", type=Path,
                  default=Path("results/graphdet_specials"))
  ap.add_argument("--cell-min", type=int, default=_GRAPH_CELL_PX,
                  help="smallest export cell to try (px)")
  ap.add_argument("--cell", type=int, default=None,
                  help="fixed export cell (px); no widening")
  ap.add_argument("--workers", type=int, default=_WORKERS)
  ap.add_argument("--variant", default=PRODUCTION,
                  help="hits: production export or dog3dz")
  ap.add_argument("--dog-k", type=float, default=2.0)
  ap.add_argument("--max-gap-frac", type=float, default=None)
  ap.add_argument("--salvage", action="store_true")
  args = ap.parse_args()
  run(args.event, args.specials, args.out,
      args.cell if args.cell else args.cell_min, args.cell is not None,
      args.workers, args.variant, args.dog_k, args.max_gap_frac,
      args.salvage)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
