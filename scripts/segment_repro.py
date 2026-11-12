"""Truth-free line-segment quality on the full scan: does the overlapping
view see the same segments?

Neighbouring full-scan views overlap by ~52 % per axis (0.5 mm stage
step, ~1.04 mm field), so the interior is imaged about four times. A
real track segment should come back at the same plate position in each
image; a noise segment should not. This script rebuilds, for a block of
views, the B' polylines (export -> stage 1 -> stage 2, production
settings of fullscan_bprime.py) and the method-A Hough segments
(find_tracks on every slice), maps them to plate coordinates and scores
how much segment length of one view is reproduced by its neighbour.

Plate coordinates: x, y in um = stage x/y (JSON encoder readback, mm)
x 1000 + PX_TO_UM @ (pixel - centre); z in um = stage z of the
(fractional) slice. PX_TO_UM is solved from the neighbour image shifts
measured by e07-g4-hypernuclei (VX+1: (+987.5, -2.6) px, VY+1:
(-1.1, -987.4) px; x flipped, ~2.6 mrad camera rotation) and scaled to
UM_PER_PX (encoder check, ed8b6da). score prints the median xy and z
offsets of matched samples per pair as a check of this mapping.

  python scripts/segment_repro.py extract [--vx 21 23 --vy 21 23]
  python scripts/segment_repro.py score
  python scripts/segment_repro.py figure [--pair 22 22 23 22]
  python scripts/segment_repro.py stages [--pair 21 22 21 23]
  python scripts/segment_repro.py gridshift --pair 21 22 0 0
  python scripts/segment_repro.py consensus --pair 21 22 0 0

stages splits the B' result by step for one pair: export hits (cached
as <stem>_hits.npy), stage-1 segments and stage-2 polylines, each
scored for reproduction by the other view and for support (share of
its length with an own hit within CELL_PX); figure stages_*.png.

Outputs under results/segment_eval/: <stem>_bprime.npz (polylines,
stage-1 segments, hit count), <stem>_A.parquet (Hough segments),
scores.csv / scores.txt, crops_*.png.
"""
import argparse
import glob
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from fullscan_bprime import VIEWS  # noqa: E402

OUT = REPO / "results/segment_eval"
# The export noise classifier is trained on these views' labels, so
# their hits are not independent of it: left out of the scores.
LABELS = REPO / "results/manual_labels"
UM_PER_PX = 0.507
# Neighbour image shifts (px) for one view step in x and in y, and the
# nominal stage step (um) they correspond to.
SHIFT_VX_PX = (987.5, -2.6)
SHIFT_VY_PX = (-1.1, -987.4)
NOMINAL_STEP_UM = 500.0
IMAGE_PX = 2048
CENTRE_PX = (IMAGE_PX - 1) / 2
UM_PER_MM = 1000.0
CELL_PX = 6
WORKERS = 12
STEP_PX = 2.0           # arc-length sampling step
EDGE_PX = 30            # keep samples this far inside the other view
MATCH_PX = (1.0, 2.0, 4.0)
MATCH_DEG = 10.0
# Control-subtracted B' matches spread with sigma ~8 um in depth
# (V00000966/V00001011, 2026-11-11), so two sigma.
MATCH_DZ_UM = 15.0
CONTROL_SHIFT_UM = 40.0
LEN_BINS_UM = (0, 10, 25, 50, 100, np.inf)
MIN_OWN_UM = 10.0       # owner length inside the overlap to be scored
OWN_REPRO = 0.5         # owner reproduced: this fraction of it matched
SLAB_UM = 20.0          # depth slab drawn by figure
GRID_SHIFT_PX = 64      # half a stage-1 sub-region
CONS_R_PX = 4.0         # consensus match radius (B' xy is coarse)
RAND_SEED = 0
OWN_EDGE_PX = 10        # B' piles up at the image border
LOOSE_DZ_UM = 30.0      # depth window for the mapping check
K_NEAREST = 32
MAX_SAMPLES = 300_000   # per pair and source (A is dense)


def view_paths(vx, vy):
  out = {}
  for x in range(vx[0], vx[1] + 1):
    for y in range(vy[0], vy[1] + 1):
      p = glob.glob(str(VIEWS / f"V*_L0_VX{x:04d}_VY{y:04d}_0_058.json"))
      if p:
        out[(x, y)] = Path(p[0])
  return out


def extract(args):
  import rank_specials as rs
  from module.graphdet import (E07_Z_SCALE, MATLAB_CONFIG,
                               integrate_smallregions)
  from module.graphdet.detectlseg import detect_lseg_view
  from module.matlab_export import export_hits_grid
  from module.track_classifier import build_training_set, train_classifier

  OUT.mkdir(parents=True, exist_ok=True)
  clf = train_classifier(*build_training_set(REPO / "results/manual_labels"))
  cfg = replace(MATLAB_CONFIG.for_spacing(float(CELL_PX)),
                z_scale=E07_Z_SCALE)
  for (x, y), path in sorted(view_paths(args.vx, args.vy).items()):
    fb = OUT / f"{path.stem}_bprime.npz"
    fa = OUT / f"{path.stem}_A.parquet"
    t0 = time.time()
    if not fb.exists():
      pl = export_hits_grid(path, cell=CELL_PX, denoise_method="classifier",
                            classifier=clf)
      hits = pl[:, :3]
      seg, _ = detect_lseg_view(hits, cfg=cfg, workers=WORKERS)
      polys = integrate_smallregions(hits, seg, cfg)
      lens = np.array([len(p) for p in polys], int)
      np.savez_compressed(
        fb, poly_xyz=np.concatenate(polys) if polys else np.zeros((0, 3)),
        poly_len=lens, lseg=np.asarray(seg), n_hits=len(hits))
    t1 = time.time()
    if not fa.exists():
      rs.tracks_of(path).drop(columns=["view_id"]).to_parquet(fa)
    print(f"{path.stem}: B' {t1 - t0:.0f} s, A {time.time() - t1:.0f} s",
          flush=True)


# ---------------------------------------------------------------- scoring

def stage_of(path):
  from module.reader import load_spng
  r = load_spng(path)
  e = r._entries[0]
  return (np.array([e.x, e.y]) * UM_PER_MM,
          r.z_positions() * UM_PER_MM)


def load_bprime(f):
  from module.matlab_export import _ORIGIN_OFFSET
  d = np.load(f)
  xyz = d["poly_xyz"] - _ORIGIN_OFFSET  # pixel x, pixel y, slice index
  return np.split(xyz, np.cumsum(d["poly_len"])[:-1])


def load_a(f):
  a = pd.read_parquet(f, columns=["px1", "py1", "px2", "py2", "slice_idx"])
  s = a.slice_idx.to_numpy(float)
  return [np.array([[r.px1, r.py1, z], [r.px2, r.py2, z]], float)
          for r, z in zip(a.itertuples(), s)]


def sample(polys):
  """Points every STEP_PX along each polyline: (x, y, slice, ux, uy,
  owner id, length weight), in pixels."""
  rows = []
  for k, p in enumerate(polys):
    for a, b in zip(p[:-1], p[1:]):
      d = b[:2] - a[:2]
      n = np.hypot(*d)
      if n == 0:
        continue
      m = max(int(np.ceil(n / STEP_PX)), 1)
      t = (np.arange(m) + 0.5) / m
      pts = a + t[:, None] * (b - a)
      u = np.broadcast_to(d / n, (m, 2))
      rows.append(np.column_stack([pts, u, np.full(m, k),
                                   np.full(m, n / m)]))
  return np.concatenate(rows) if rows else np.zeros((0, 7))


def px_to_um():
  # Same plate point: A @ (p_next - p) = stage - stage_next.
  d = np.column_stack([SHIFT_VX_PX, SHIFT_VY_PX])
  a = -NOMINAL_STEP_UM * np.linalg.inv(d)
  return a / np.sqrt(abs(np.linalg.det(a))) * UM_PER_PX


PX_TO_UM = px_to_um()
UM_TO_PX = np.linalg.inv(PX_TO_UM)


def to_plate(s, stage_xy, stage_z):
  xy = stage_xy + (s[:, :2] - CENTRE_PX) @ PX_TO_UM.T
  z = np.interp(s[:, 2], np.arange(len(stage_z)), stage_z)
  u = s[:, 3:5] @ PX_TO_UM.T
  return xy, z, u / np.linalg.norm(u, axis=1, keepdims=True)


def to_px(xy, stage_xy):
  return (xy - stage_xy) @ UM_TO_PX.T + CENTRE_PX


def inside(xy, stage_xy, margin_px):
  px = to_px(xy, stage_xy)
  return ((px >= margin_px) & (px < IMAGE_PX - margin_px)).all(axis=1)


def best_match(src, dst, r_um, dz_tol, shift=(0.0, 0.0), dz0=0.0,
               deg=None):
  """Per src sample: xy distance to the nearest dst sample within r_um
  that also agrees in direction (MATCH_DEG) and depth (|dz - dz0| <=
  dz_tol), inf if none, and that sample's (dx, dy, dz)."""
  tree, z_dst, u_dst = dst
  xy, z, u = src
  d, j = tree.query(xy + shift, k=K_NEAREST, distance_upper_bound=r_um)
  ok = j < tree.n
  jj = np.where(ok, j, 0)
  dz = z_dst[jj] - z[:, None]
  cos = np.abs(np.einsum("nkc,nc->nk", u_dst[jj], u))
  deg = MATCH_DEG if deg is None else deg
  ok &= (np.abs(dz - dz0) <= dz_tol) & (cos >= np.cos(np.radians(deg)))
  d = np.where(ok, d, np.inf)
  k = d.argmin(axis=1)
  n = np.arange(len(xy))
  off = np.column_stack([tree.data[jj[n, k]] - xy - shift, dz[n, k]])
  return d[n, k], off


def overlap(sa, sb, ga, gb):
  """View-a samples (plate coordinates) inside view b, away from both
  borders, their length weights and owners; view b as a search tree."""
  pa = to_plate(sa, *ga)
  pb = to_plate(sb, *gb)
  keep = (inside(pa[0], gb[0], EDGE_PX)
          & inside(pa[0], ga[0], OWN_EDGE_PX))
  if keep.sum() > MAX_SAMPLES:
    # Subsample whole owners, so per-owner fractions stay exact.
    owners = sa[:, 5].astype(int)
    pick = np.random.default_rng(RAND_SEED).random(owners.max() + 1)
    keep &= pick[owners] < MAX_SAMPLES / keep.sum()
  idx = np.flatnonzero(keep)
  src = tuple(v[idx] for v in pa)
  dst = (cKDTree(pb[0]), pb[1], pb[2])
  return src, dst, sa[idx, 6], sa[idx, 5].astype(int)


def score(args):
  paths = view_paths(args.vx, args.vy)
  geo = {k: stage_of(p) for k, p in paths.items()}
  labelled = {f.name.split("__")[-2].split(".")[0]
              for f in LABELS.glob("*.json")}
  segs = {}
  for k, p in paths.items():
    if p.stem in labelled:
      print(f"skip {p.stem} (classifier training labels)")
      continue
    fb = OUT / f"{p.stem}_bprime.npz"
    fa = OUT / f"{p.stem}_A.parquet"
    if fb.exists() and fa.exists():
      segs[k] = {"Bprime": sample(load_bprime(fb)), "A": sample(load_a(fa))}
  pairs = [(a, b) for a in segs for b in segs
           if a != b and abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) <= 1]
  if not pairs:
    sys.exit("no neighbouring views extracted")
  r_max = max(MATCH_PX) * UM_PER_PX
  rows = []
  for a, b in pairs:
    # Mapping check on B': offsets of matches with a loose depth window.
    src, dst, w, _ = overlap(segs[a]["Bprime"], segs[b]["Bprime"],
                             geo[a], geo[b])
    d, off = best_match(src, dst, r_max, LOOSE_DZ_UM)
    m = np.isfinite(d)
    dz0 = float(np.median(off[m, 2])) if m.any() else 0.0
    q = np.percentile(off[m], (16, 50, 84), axis=0) if m.any() else None
    print(f"{a}->{b}: B' offset median dx {q[1, 0]:+.2f} dy {q[1, 1]:+.2f}"
          f" dz {q[1, 2]:+.2f} um (16-84 % dz {q[0, 2]:+.1f}..{q[2, 2]:+.1f})"
          if q is not None else f"{a}->{b}: no B' match", flush=True)
    for src_name in ("Bprime", "A"):
      src, dst, w, owner = overlap(segs[a][src_name], segs[b][src_name],
                                   geo[a], geo[b])
      d_abs, _ = best_match(src, dst, r_max, MATCH_DZ_UM)
      d, _ = best_match(src, dst, r_max, MATCH_DZ_UM, dz0=dz0)
      dc, _ = best_match(src, dst, r_max, MATCH_DZ_UM, dz0=dz0,
                         shift=(CONTROL_SHIFT_UM, CONTROL_SHIFT_UM))
      for r in MATCH_PX:
        r_um = r * UM_PER_PX
        row = {"source": src_name, "view": a, "other": b, "r_px": r,
               "dz0_um": dz0, "repro": wfrac(w, d <= r_um),
               "repro_abs_z": wfrac(w, d_abs <= r_um),
               "control": wfrac(w, dc <= r_um)}
        own, own_c = owner_repro(owner, w, d <= r_um, dc <= r_um)
        row["own_repro"] = np.mean(own[0]) if len(own[0]) else np.nan
        row["own_control"] = (np.mean(own_c[0]) if len(own_c[0])
                              else np.nan)
        for lo, hi in zip(LEN_BINS_UM[:-1], LEN_BINS_UM[1:]):
          s = (own[1] >= lo) & (own[1] < hi)
          row[f"own_{lo:g}-{hi:g}um"] = (np.mean(own[0][s]) if s.any()
                                         else np.nan)
        rows.append(row)
  out = pd.DataFrame(rows)
  out.to_csv(OUT / "scores.csv", index=False)
  lines = [f"{UM_PER_PX} um/px, step {STEP_PX} px, angle {MATCH_DEG} deg,"
           f" dz {MATCH_DZ_UM} um around the pair's median B' dz,"
           f" control shift {CONTROL_SHIFT_UM} um, {len(pairs)} pairs",
           "median per-pair dz0 {:+.2f} um (range {:+.2f}..{:+.2f})".format(
             out.dz0_um.median(), out.dz0_um.min(), out.dz0_um.max())]
  for (src, r), g in out.groupby(["source", "r_px"]):
    cols = [c for c in g.columns if c.startswith("own_")
            and c[4].isdigit()]
    lines.append(f"{src} r {r:g} px: length reproduced "
                 f"{g.repro.mean():.1%} (absolute z "
                 f"{g.repro_abs_z.mean():.1%}, control "
                 f"{g.control.mean():.1%}); segments >= {OWN_REPRO:.0%} "
                 f"reproduced {g.own_repro.mean():.1%} (control "
                 f"{g.own_control.mean():.1%}), by length "
                 + ", ".join(f"{c[4:]} {g[c].mean():.1%}" for c in cols))
  for s in ("Bprime", "A"):
    c = [len(np.unique(segs[k][s][:, 5])) for k in segs]
    tot = [segs[k][s][:, 6].sum() * UM_PER_PX / UM_PER_MM for k in segs]
    lines.append(f"{s}: segments per view median {np.median(c):.0f}, "
                 f"total length per view median {np.median(tot):.0f} mm")
  text = "\n".join(lines) + "\n"
  print(text, end="")
  (OUT / "scores.txt").write_text(text)


def owner_repro(owner, w, hit, hit_c):
  """Per owner with >= MIN_OWN_UM inside the overlap: (reproduced?,
  overlap length um), for the match and the control."""
  n = owner.max() + 1 if len(owner) else 0
  tot = np.bincount(owner, weights=w, minlength=n)
  keep = tot * UM_PER_PX >= MIN_OWN_UM
  out = []
  for h in (hit, hit_c):
    f = np.bincount(owner, weights=w * h, minlength=n)[keep] / tot[keep]
    out.append((f >= OWN_REPRO, tot[keep] * UM_PER_PX))
  return out


def wfrac(w, ok):
  return float((w * ok).sum() / w.sum()) if w.sum() > 0 else np.nan


def figure(args):
  """Same plate patches seen from two neighbouring views, in a depth
  slab of SLAB_UM around the middle of view a: minimum projection of
  the slab with B' polylines (left pair) and A segments (right pair),
  green when the other view reproduces >= OWN_REPRO of the segment's
  length inside the patch (r_px, MATCH_DEG, MATCH_DZ_UM), red when not.
  Patches sit in the overlap, picked at random."""
  import matplotlib
  matplotlib.use("Agg")
  import matplotlib.pyplot as plt
  from module.reader import load_spng

  paths = view_paths(args.vx, args.vy)
  a, b = tuple(args.pair[:2]), tuple(args.pair[2:])
  geo = {k: stage_of(paths[k]) for k in (a, b)}
  z_mid = np.median(geo[a][1])
  slab = (z_mid - SLAB_UM / 2, z_mid + SLAB_UM / 2)
  imgs, polys, samp = {}, {}, {}
  for k in (a, b):
    sz = geo[k][1]
    ks = np.flatnonzero((sz >= slab[0]) & (sz <= slab[1]))
    imgs[k] = load_spng(paths[k]).read_stack()[ks].min(axis=0)
    polys[k] = {"Bprime": load_bprime(OUT / f"{paths[k].stem}_bprime.npz"),
                "A": load_a(OUT / f"{paths[k].stem}_A.parquet")}
    samp[k] = {s: sample(v) for s, v in polys[k].items()}
  rng = np.random.default_rng(RAND_SEED)
  half = args.patch_px / 2 * UM_PER_PX
  lo = np.maximum(geo[a][0], geo[b][0]) - (IMAGE_PX / 2 - EDGE_PX) * UM_PER_PX
  hi = np.minimum(geo[a][0], geo[b][0]) + (IMAGE_PX / 2 - EDGE_PX) * UM_PER_PX
  centres = rng.uniform(lo + half, hi - half, (args.n_patch, 2))
  r_um = args.r_px * UM_PER_PX
  fig, axes = plt.subplots(args.n_patch, 4,
                           figsize=(16, 4 * args.n_patch), squeeze=False)
  for row, c in zip(axes, centres):
    for ax, (k, src) in zip(row, [(a, "Bprime"), (b, "Bprime"),
                                  (a, "A"), (b, "A")]):
      o = b if k == a else a
      xy, z, u = to_plate(samp[k][src], *geo[k])
      m = ((np.abs(xy - c) <= half).all(axis=1)
           & (z >= slab[0]) & (z <= slab[1]))
      pb = to_plate(samp[o][src], *geo[o])
      d, _ = best_match((xy[m], z[m], u[m]), (cKDTree(pb[0]), pb[1], pb[2]),
                        r_um, MATCH_DZ_UM)
      owner = samp[k][src][m, 5].astype(int)
      w = samp[k][src][m, 6]
      n = owner.max() + 1 if len(owner) else 0
      tot = np.bincount(owner, weights=w, minlength=n)
      hit = np.bincount(owner, weights=w * (d <= r_um), minlength=n)
      px0 = to_px(c[None], geo[k][0])[0]
      x0, y0 = (px0 - args.patch_px / 2).astype(int)
      crop = imgs[k][y0:y0 + args.patch_px, x0:x0 + args.patch_px]
      ax.imshow(crop, cmap="gray", extent=(x0, x0 + args.patch_px,
                                           y0 + args.patch_px, y0))
      n_ok = 0
      for j in np.flatnonzero(tot > 0):
        ok = hit[j] / tot[j] >= OWN_REPRO
        n_ok += ok
        p = polys[k][src][j]
        ax.plot(p[:, 0], p[:, 1], "-", color="lime" if ok else "red",
                lw=0.8, alpha=0.8)
      ax.set_xlim(x0, x0 + args.patch_px)
      ax.set_ylim(y0 + args.patch_px, y0)
      ax.set_title(f"{src} VX{k[0]} VY{k[1]} ({c[0]:.0f}, {c[1]:.0f}) um: "
                   f"{n_ok}/{(tot > 0).sum()} reproduced", fontsize=9)
      ax.set_xticks([])
      ax.set_yticks([])
  fig.suptitle(f"depth slab {slab[0]:.0f}..{slab[1]:.0f} um, "
               f"r {args.r_px:g} px, {MATCH_DEG:g} deg, dz {MATCH_DZ_UM:g} um")
  fig.tight_layout()
  f = OUT / f"crops_VX{a[0]}VY{a[1]}_VX{b[0]}VY{b[1]}.png"
  fig.savefig(f, dpi=110)
  print(f)


def load_hits(path):
  """Export hits of a view (pixel x, pixel y, slice), cached."""
  from module.matlab_export import _ORIGIN_OFFSET, export_hits_grid
  from module.track_classifier import build_training_set, train_classifier
  f = OUT / f"{path.stem}_hits.npy"
  if not f.exists():
    clf = train_classifier(*build_training_set(LABELS))
    pl = export_hits_grid(path, cell=CELL_PX, denoise_method="classifier",
                          classifier=clf)
    np.save(f, (pl[:, :3] - _ORIGIN_OFFSET).astype(np.float32))
  return np.load(f).astype(float)


def load_lseg(f):
  from module.matlab_export import _ORIGIN_OFFSET
  e = np.load(f)["lseg"] - _ORIGIN_OFFSET
  return [e[:, :, m] for m in range(e.shape[2])]


def hit_samples(h):
  # Points as zero-direction samples: own id, unit weight.
  n = len(h)
  return np.column_stack([h, np.ones(n), np.zeros(n), np.arange(n),
                          np.ones(n)])


def stage_sets(path):
  fb = OUT / f"{path.stem}_bprime.npz"
  h = load_hits(path)
  return {"hits": ([p[None] for p in h], hit_samples(h)),
          "lseg": (load_lseg(fb), sample(load_lseg(fb))),
          "poly": (load_bprime(fb), sample(load_bprime(fb)))}


def stages(args):
  import matplotlib
  matplotlib.use("Agg")
  import matplotlib.pyplot as plt
  from module.reader import load_spng

  paths = view_paths(args.vx, args.vy)
  a, b = tuple(args.pair[:2]), tuple(args.pair[2:])
  geo = {k: stage_of(paths[k]) for k in (a, b)}
  sets = {k: stage_sets(paths[k]) for k in (a, b)}
  lines = [f"pair {a} {b}, dz {MATCH_DZ_UM} um, angle {MATCH_DEG} deg "
           f"(hits: none), support radius {CELL_PX} px"]
  for name in ("hits", "lseg", "poly"):
    deg = 90.0 if name == "hits" else None
    for k, o in ((a, b), (b, a)):
      src, dst, w, owner = overlap(sets[k][name][1], sets[o][name][1],
                                   geo[k], geo[o])
      # Support: own hits near the sample, any direction.
      hk = to_plate(sets[k]["hits"][1], *geo[k])
      hdst = (cKDTree(hk[0]), hk[1], hk[2])
      sup, _ = best_match(src, hdst, CELL_PX * UM_PER_PX, MATCH_DZ_UM,
                          deg=90.0)
      parts = [f"{name} {k}->{o}: n {len(sets[k][name][0])}"]
      for r in MATCH_PX[1:]:
        r_um = r * UM_PER_PX
        d, _ = best_match(src, dst, r_um, MATCH_DZ_UM, deg=deg)
        dc, _ = best_match(src, dst, r_um, MATCH_DZ_UM, deg=deg,
                           shift=(CONTROL_SHIFT_UM, CONTROL_SHIFT_UM))
        own, own_c = owner_repro(owner, w, d <= r_um, dc <= r_um)
        parts.append(f"r {r:g} px: length {wfrac(w, d <= r_um):.1%} "
                     f"(ctl {wfrac(w, dc <= r_um):.1%}), items "
                     f"{np.mean(own[0]):.1%} (ctl {np.mean(own_c[0]):.1%})")
      parts.append(f"support {wfrac(w, np.isfinite(sup)):.1%}")
      lines.append("; ".join(parts))
  text = "\n".join(lines) + "\n"
  print(text, end="")
  (OUT / f"stages_VX{a[0]}VY{a[1]}_VX{b[0]}VY{b[1]}.txt").write_text(text)

  # Figure: patches in the overlap, depth slab around view a's middle.
  z_mid = np.median(geo[a][1])
  slab = (z_mid - SLAB_UM / 2, z_mid + SLAB_UM / 2)
  rng = np.random.default_rng(RAND_SEED)
  half = args.patch_px / 2 * UM_PER_PX
  lo = np.maximum(geo[a][0], geo[b][0]) - (IMAGE_PX / 2 - EDGE_PX) * UM_PER_PX
  hi = np.minimum(geo[a][0], geo[b][0]) + (IMAGE_PX / 2 - EDGE_PX) * UM_PER_PX
  centres = rng.uniform(lo + half, hi - half, (args.n_patch, 2))
  r_um = args.r_px * UM_PER_PX
  imgs = {}
  for k in (a, b):
    sz = geo[k][1]
    ks = np.flatnonzero((sz >= slab[0]) & (sz <= slab[1]))
    imgs[k] = load_spng(paths[k]).read_stack()[ks].min(axis=0)
  cols = [(k, n) for k in (a, b) for n in ("hits", "lseg", "poly")]
  fig, axes = plt.subplots(args.n_patch, len(cols),
                           figsize=(4 * len(cols), 4 * args.n_patch),
                           squeeze=False)
  for row, c in zip(axes, centres):
    for ax, (k, name) in zip(row, cols):
      o = b if k == a else a
      items, s = sets[k][name]
      xy, z, u = to_plate(s, *geo[k])
      m = ((np.abs(xy - c) <= half).all(axis=1)
           & (z >= slab[0]) & (z <= slab[1]))
      pb = to_plate(sets[o][name][1], *geo[o])
      d, _ = best_match((xy[m], z[m], u[m]), (cKDTree(pb[0]), pb[1], pb[2]),
                        r_um, MATCH_DZ_UM,
                        deg=90.0 if name == "hits" else None)
      owner = s[m, 5].astype(int)
      w = s[m, 6]
      n = owner.max() + 1 if len(owner) else 0
      tot = np.bincount(owner, weights=w, minlength=n)
      hit = np.bincount(owner, weights=w * (d <= r_um), minlength=n)
      px0 = to_px(c[None], geo[k][0])[0]
      x0, y0 = (px0 - args.patch_px / 2).astype(int)
      ax.imshow(imgs[k][y0:y0 + args.patch_px, x0:x0 + args.patch_px],
                cmap="gray", extent=(x0, x0 + args.patch_px,
                                     y0 + args.patch_px, y0))
      js = np.flatnonzero(tot > 0)
      ok = hit[js] / tot[js] >= OWN_REPRO
      if name == "hits":
        p = np.array([items[j][0] for j in js]).reshape(-1, 3)
        ax.scatter(p[:, 0], p[:, 1], s=2, lw=0,
                   c=np.where(ok, "lime", "red"))
      else:
        for j, g in zip(js, ok):
          q = items[j]
          ax.plot(q[:, 0], q[:, 1], "-", color="lime" if g else "red",
                  lw=0.8, alpha=0.8)
      ax.set_xlim(x0, x0 + args.patch_px)
      ax.set_ylim(y0 + args.patch_px, y0)
      ax.set_title(f"{name} VX{k[0]} VY{k[1]}: {ok.sum()}/{len(js)} "
                   "reproduced", fontsize=9)
      ax.set_xticks([])
      ax.set_yticks([])
  fig.suptitle(f"depth slab {slab[0]:.0f}..{slab[1]:.0f} um, "
               f"r {args.r_px:g} px, dz {MATCH_DZ_UM:g} um")
  fig.tight_layout()
  f = OUT / f"stages_VX{a[0]}VY{a[1]}_VX{b[0]}VY{b[1]}.png"
  fig.savefig(f, dpi=100)
  print(f)


def gridshift(args):
  """Rerun stages 1 and 2 on one view's own hits with the sub-region grid
  moved by GRID_SHIFT_PX in x and y, and score how much of the original
  output the shifted run reproduces (same image, only the grid moved).
  Only the part away from both grids' edges is scored."""
  from module.graphdet import (E07_Z_SCALE, MATLAB_CONFIG,
                               integrate_smallregions)
  from module.graphdet.detectlseg import (N_REGIONS, REGION_PX,
                                          detect_lseg_view)
  from module.matlab_export import _ORIGIN_OFFSET

  paths = view_paths(args.vx, args.vy)
  k = tuple(args.pair[:2])
  path = paths[k]
  cfg = replace(MATLAB_CONFIG.for_spacing(float(CELL_PX)),
                z_scale=E07_Z_SCALE)
  f = OUT / f"{path.stem}_gridshift.npz"
  if not f.exists():
    x = load_hits(path) + _ORIGIN_OFFSET
    sh = np.array([GRID_SHIFT_PX, GRID_SHIFT_PX, 0.0])
    seg, _ = detect_lseg_view(x + sh, cfg=cfg, workers=WORKERS)
    polys = integrate_smallregions(x + sh, seg, cfg)
    seg = seg - sh[None, :, None]
    polys = [q - sh for q in polys]
    np.savez_compressed(
      f, poly_xyz=np.concatenate(polys), poly_len=[len(q) for q in polys],
      lseg=seg)
  g = stage_of(path)
  fb = OUT / f"{path.stem}_bprime.npz"
  sets = {"lseg": (sample(load_lseg(fb)), sample(load_lseg(f))),
          "poly": (sample(load_bprime(fb)), sample(load_bprime(f)))}
  grid_end = REGION_PX * N_REGIONS - GRID_SHIFT_PX
  lines = [f"{path.stem}: grid shifted by {GRID_SHIFT_PX} px, scored in "
           f"x, y [{GRID_SHIFT_PX + EDGE_PX}, {grid_end - EDGE_PX}) px"]
  for name, (s0, s1) in sets.items():
    for tag, a, b in (("orig->shift", s0, s1), ("shift->orig", s1, s0)):
      keep = ((a[:, :2] >= GRID_SHIFT_PX + EDGE_PX)
              & (a[:, :2] < grid_end - EDGE_PX)).all(axis=1)
      pa = to_plate(a[keep], *g)
      pb = to_plate(b, *g)
      dst = (cKDTree(pb[0]), pb[1], pb[2])
      w, owner = a[keep, 6], a[keep, 5].astype(int)
      parts = [f"{name} {tag}"]
      for r in MATCH_PX[1:]:
        r_um = r * UM_PER_PX
        d, _ = best_match(pa, dst, r_um, MATCH_DZ_UM)
        own, _ = owner_repro(owner, w, d <= r_um, d <= r_um)
        parts.append(f"r {r:g} px: length {wfrac(w, d <= r_um):.1%}, "
                     f"items {np.mean(own[0]):.1%}")
      lines.append("; ".join(parts))
  text = "\n".join(lines) + "\n"
  print(text, end="")
  (OUT / f"gridshift_{path.stem}.txt").write_text(text)


def consensus(args):
  """Cross-view consensus for one view's B' polylines: for each polyline,
  the other views of the block that image most of it (>= OWN_REPRO of
  its length inside them, away from their edges) and how many of those
  reproduce >= OWN_REPRO of it (r CONS_R_PX, MATCH_DEG, MATCH_DZ_UM).
  Kept: reproduced by >= 1 view, or imaged by no other view. Stage 3 is
  rerun on all and on the kept polylines to compare branch points.
  Writes consensus_<stem>.csv (per polyline) and .txt."""
  from module.graphdet import (E07_Z_SCALE, MATLAB_CONFIG,
                               attachment_codes, branch_points)
  from module.matlab_export import _ORIGIN_OFFSET

  paths = view_paths(args.vx, args.vy)
  labelled = {f.name.split("__")[-2].split(".")[0]
              for f in LABELS.glob("*.json")}
  k = tuple(args.pair[:2])
  others = [o for o in paths if o != k and paths[o].stem not in labelled
            and (OUT / f"{paths[o].stem}_bprime.npz").exists()]
  polys = load_bprime(OUT / f"{paths[k].stem}_bprime.npz")
  s = sample(polys)
  gk = stage_of(paths[k])
  src = to_plate(s, *gk)
  owner, w = s[:, 5].astype(int), s[:, 6]
  n = len(polys)
  tot = np.bincount(owner, weights=w, minlength=n)
  n_cover = np.zeros(n, int)
  n_repro = np.zeros(n, int)
  r_um = CONS_R_PX * UM_PER_PX
  for o in others:
    go = stage_of(paths[o])
    so = sample(load_bprime(OUT / f"{paths[o].stem}_bprime.npz"))
    po = to_plate(so, *go)
    ins = inside(src[0], go[0], EDGE_PX)
    cover = np.bincount(owner, weights=w * ins, minlength=n) / tot
    d, _ = best_match(tuple(v[ins] for v in src),
                      (cKDTree(po[0]), po[1], po[2]), r_um, MATCH_DZ_UM)
    rep = np.bincount(owner[ins], weights=w[ins] * (d <= r_um),
                      minlength=n) / tot
    c = cover >= OWN_REPRO
    n_cover += c
    n_repro += c & (rep >= OWN_REPRO * cover)
  length = tot * UM_PER_PX
  keep = (n_repro >= 1) | (n_cover == 0)
  pd.DataFrame({"length_um": length, "n_cover": n_cover,
                "n_repro": n_repro, "keep": keep}).to_csv(
    OUT / f"consensus_{paths[k].stem}.csv", index=False)

  cfg = replace(MATLAB_CONFIG.for_spacing(float(CELL_PX)),
                z_scale=E07_Z_SCALE)
  x = load_hits(paths[k]) + _ORIGIN_OFFSET
  raw = [q + _ORIGIN_OFFSET for q in polys]
  bp = {}
  for tag, sel in (("all", raw),
                   ("kept", [q for q, g in zip(raw, keep) if g])):
    pts, _ = branch_points(sel, x, attachment_codes(sel, x, cfg), cfg)
    bp[tag] = len(pts)
  cov = n_cover >= 1
  lines = [f"{paths[k].stem}: {n} polylines, other views "
           f"{[o for o in others]}, r {CONS_R_PX} px, dz {MATCH_DZ_UM} um",
           f"imaged by >= 1 other view: {cov.sum()} ({cov.mean():.1%}); "
           f"of those reproduced by >= 1: "
           f"{(n_repro[cov] >= 1).mean():.1%}",
           f"kept {keep.sum()} ({keep.mean():.1%}), kept length "
           f"{length[keep].sum() / UM_PER_MM:.0f} of "
           f"{length.sum() / UM_PER_MM:.0f} mm",
           f"branch points: all {bp['all']}, kept {bp['kept']}"]
  for lo, hi in zip(LEN_BINS_UM[:-1], LEN_BINS_UM[1:]):
    m = cov & (length >= lo) & (length < hi)
    if m.any():
      lines.append(f"  length {lo:g}-{hi:g} um: {m.sum()} imaged, "
                   f"reproduced {(n_repro[m] >= 1).mean():.1%}, "
                   f"by >= 2 {(n_repro[m] >= 2).mean():.1%}")
  text = "\n".join(lines) + "\n"
  print(text, end="")
  (OUT / f"consensus_{paths[k].stem}.txt").write_text(text)


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("step", choices=["extract", "score", "figure",
                                       "stages", "gridshift",
                                       "consensus"])
  ap.add_argument("--pair", type=int, nargs=4, default=(22, 22, 23, 22),
                  help="figure: VX VY of two neighbouring views")
  ap.add_argument("--patch-px", type=int, default=300)
  ap.add_argument("--n-patch", type=int, default=3)
  ap.add_argument("--r-px", type=float, default=MATCH_PX[1])
  ap.add_argument("--vx", type=int, nargs=2, default=(21, 23))
  ap.add_argument("--vy", type=int, nargs=2, default=(21, 23))
  args = ap.parse_args()
  {"extract": extract, "score": score, "figure": figure,
   "stages": stages, "gridshift": gridshift,
   "consensus": consensus}[args.step](args)


if __name__ == "__main__":
  main()
