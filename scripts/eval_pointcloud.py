"""Score the point cloud handed to the graph detector against grain truth.

The graph detector only ever sees the hits ``export_hits_grid`` makes,
so a track lost or a junk hit added before it cannot be repaired later.
This measures that stage on its own, one cumulative step at a time, so
the step that loses real grains (or lets junk through) shows up:

  otsu        fog removal + Otsu, nothing else
  speck       + removal of specks only (area < noise_amin)
  blob        + full small-blob removal (remove_noise) = denoise "off"
  legacy      + Hough-alignment filter (denoise "legacy")
  threshold   + segment filter, two cut-offs (denoise "threshold")
  classifier  + segment filter, trained model (denoise "classifier")
  otsu_rand   otsu hits thinned at random to the classifier's count:
              what a filter that knows nothing would do at that budget
  dog         grain detector instead of Otsu: difference of Gaussians
              at grain scale on the fog-removed slice, one hit per
              local maximum above DOG_K robust sigmas
  dog3d       the same maxima kept only if they are also the maximum
              over the slices either side, so a grain seen in three
              slices gives one hit at its sharpest slice
  dog3dz      dog3d with a sub-slice z from a parabola through the
              responses of the slices within FIT_HALF of it: the
              optics barely dim a grain one slice (~4 um) out of
              focus, so the sharpest slice alone is good to +-1 slice
  ridge       line detector: elongated oriented filters (a ridge
              profile across, a long Gaussian along, RIDGE_ANGLES
              directions), thresholded at RIDGE_K robust sigmas; centre
              lines at least RIDGE_MIN_LEN_PX long, sampled every cell
              px. Real flat tracks are smooth faint grey lines with no
              grain maxima along them, which DoG misses, and a local
              (Hessian) curvature is lost in the background texture --
              they only stand out when integrated along their length
  ridge3d     ridge hits kept only where the line is at least as strong
              as in the slices either side (its sharpest slice)
  dogridge    dog3d plus the ridge3d hits farther than COVER_R_PX from
              any dog3d hit in the same slice
  otsu3d      otsu (blob3d: blob) hits kept only where the smoothed
  blob3d      darkness is at least the 3x3 maximum of the slices either
              side -- the same one-hit-per-grain z suppression as dog3d,
              without the DoG detector

Each mask is reduced to hits with ``weighted_grid_hits`` at the
production cell. Truth is e07-g4-hypernuclei's ``grains.npz`` (one row
per rendered grain: view col/row/slice, developed-emulsion um, track
instance, class, fog flag). A grain is in reach of a hit when it lies
within r px in x/y and Z_TOL_SLICES of the hit's slice -- an average
grain is visible over about +-1 slice of focus.

  purity_rN   hits with a track grain (class 1-4, not fog) in reach at
              r = N; fog_rN the same for fog grains only; chance_rN for
              the hits shifted by SHIFT_PX
  multi       hits with grains of two or more tracks in reach (r = 3)
  recall_*    visible grains (inside the image and the stack, not fog)
              with a hit in reach (r = 3), by class
  dup_med     median hits in reach of a recalled grain
  per track   grain recall, tracks lost outright, and the largest gap
              along the track's axis beyond the gap already present
              between its grains (new_gap_um); written per track too
  budget      hits per graph-detector region (max, 90th percentile)
  seconds     mask time of the steps a variant needs, plus sampling

  python scripts/eval_pointcloud.py EVENT_DIR [...] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from scipy.ndimage import maximum_filter
from scipy.spatial import cKDTree
from skimage.morphology import remove_small_objects, skeletonize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.device import default_device
from module.matlab_export import (
  _GRAPH_CELL_PX, _GRID_CELL_PX, remove_unaligned_noise,
  remove_unaligned_noise_v2, weighted_grid_hits,
)
from module.preprocess import (
  _NOISE_AMIN, fog_remove, otsu_binarize, remove_noise,
)
from module.reader import load_spng
from module.track_classifier import build_training_set, train_classifier

_LABELS_DIR = Path(__file__).resolve().parents[1] / "results/manual_labels"
MASK_VARIANTS = ("otsu", "speck", "blob", "legacy", "threshold",
                 "classifier")
# The step each mask variant is built on.
PARENT = {"speck": "otsu", "blob": "otsu", "legacy": "blob",
          "threshold": "blob", "classifier": "blob"}
RADII_PX = (1, 2, 3, 5)
COVER_R_PX = 3
Z_TOL_SLICES = 1
# Chance control: hits moved by a fixed offset (wrapping), far beyond
# any track width and off the sampling grid.
SHIFT_PX = 517
# Graph-detector sub-region (module/graphdet/detectlseg.py).
REGION_PX = 128
REGION_Z = 80
# Tracks with fewer visible grains than this are too short to judge.
MIN_TRACK_GRAINS = 5
# Grains looked at per hit when counting the tracks in reach.
MULTI_K = 8
SEED = 20261026
# Grain detector: a focused grain is a Gaussian of sigma ~1 px, blurred
# by the optics to ~1.2 px; the outer scale only has to remove the
# local background left after fog removal.
DOG_SIGMA_IN_PX = 1.2
DOG_SIGMA_OUT_PX = 3.0
DOG_K = 3.0
# Neighbourhood (px) a maximum must win; about one grain diameter.
DOG_PEAK_PX = 5
_MAD_TO_SIGMA = 1.4826
DOG_VARIANTS = ("dog", "dog3d", "dog3dz")
# dog3dz: dog3d with z refined by a parabola fitted to the responses
# of the slices within FIT_HALF of the kept one.
FIT_HALF = 2
# The fitted peak may lie in a neighbour slice when the depth profile
# is flat (the kept maximum is then a noise pick), but not beyond.
MAX_SUBSLICE = 1.0
# Line detector: cross-section and along-line sigmas (px). Chosen by
# eye on a real view: (1.5, 8) and (2.5, 12) behave alike, and K = 3
# already picks up the background texture where K = 4 does not.
RIDGE_SIGMA_CROSS_PX = 2.5
RIDGE_SIGMA_ALONG_PX = 12.0
RIDGE_ANGLES = 16
RIDGE_K = 4.0
RIDGE_MIN_LEN_PX = 30
# Components smaller than this are removed before thinning.
RIDGE_MIN_AREA_PX = 40
_KERNEL_HALF_SIGMAS = 3
RIDGE_VARIANTS = ("ridge", "ridge3d", "dogridge")
# z suppression of mask hits: darkness smoothed at grain scale.
FOCUS_SIGMA_PX = 1.2
ZSUP_VARIANTS = {"otsu3d": "otsu", "blob3d": "blob"}
CLASS_NAMES = {1: "capture", 2: "decay", 3: "secondary", 4: "background",
               5: "junk"}


def slice_masks(img, variants, clf):
  """Fog image, mask per variant, and seconds spent per step."""
  t = time.time()
  fog = fog_remove(img)
  _, otsu = otsu_binarize(fog)
  out, secs = {"otsu": otsu}, {"otsu": time.time() - t}
  steps = {
    "speck": lambda: remove_noise(otsu, noise_amax=0),
    "blob": lambda: remove_noise(otsu),
    "legacy": lambda: remove_unaligned_noise(out["blob"],
                                             cell=_GRID_CELL_PX),
    "threshold": lambda: remove_unaligned_noise_v2(
      out["blob"], fog, cell=_GRID_CELL_PX, method="threshold"),
    "classifier": lambda: remove_unaligned_noise_v2(
      out["blob"], fog, cell=_GRID_CELL_PX, method="classifier",
      classifier=clf),
  }
  need = set(variants)
  for v in variants:
    while v in PARENT:
      v = PARENT[v]
      need.add(v)
  for v in ("speck", "blob", "legacy", "threshold", "classifier"):
    if v in need:
      t = time.time()
      out[v] = steps[v]()
      secs[v] = time.time() - t
  return fog, out, secs


def chain_seconds(v, secs):
  """Mask seconds of a variant including the steps it is built on."""
  total = secs.get(v, 0.0)
  while v in PARENT:
    v = PARENT[v]
    total += secs.get(v, 0.0)
  return total


def band_trees(pts_xy, slices, n_slices):
  """Per slice s, a 2-D tree of the points within Z_TOL_SLICES of s."""
  out = []
  for s in range(n_slices):
    m = np.abs(slices - s) <= Z_TOL_SLICES
    idx = np.flatnonzero(m)
    out.append((cKDTree(pts_xy[idx]) if idx.size else None, idx))
  return out


def grain_scores(h3, g, shape, n_slices):
  """Hit-to-grain matching; returns (summary dict, per-track table)."""
  h, w = shape
  res = {}
  trk = (g["cls"] >= 1) & (g["cls"] <= 4) & ~g["fog"]
  gxy = np.column_stack([g["col"], g["row"]])
  gs = g["focus_slice"].astype(int)
  hz = hit_slices(h3, n_slices)
  shifted = np.column_stack([(h3[:, 0] + SHIFT_PX) % w,
                             (h3[:, 1] + SHIFT_PX) % h])
  rmax = max(RADII_PX)
  sets = {"trk": trk, "fog": g["fog"]}
  d = {k: np.full(len(h3), np.inf) for k in ("trk", "fog", "chance")}
  multi = np.zeros(len(h3), bool)
  # Nearest track grain of each hit (global grain index, -1 if none)
  near_g = np.full(len(h3), -1)
  for name, sel in sets.items():
    gi = np.flatnonzero(sel)
    for s, (tree, idx) in enumerate(band_trees(gxy[sel], gs[sel],
                                               n_slices)):
      hm = np.flatnonzero(hz == s)
      if tree is None or not hm.size:
        continue
      dd, jj = tree.query(h3[hm, :2], distance_upper_bound=rmax)
      d[name][hm] = dd
      if name == "trk":
        ok = dd <= COVER_R_PX
        near_g[hm[ok]] = gi[idx[jj[ok]]]
        d["chance"][hm] = tree.query(shifted[hm],
                                     distance_upper_bound=rmax)[0]
        dk, jk = tree.query(h3[hm, :2], k=MULTI_K,
                            distance_upper_bound=COVER_R_PX)
        ok = np.isfinite(dk)
        inst_all = g["instance"][sel][idx]
        ins = np.where(ok, inst_all[np.minimum(jk, len(idx) - 1)], 0)
        ins = np.sort(ins, axis=1)
        distinct = ((np.diff(ins, axis=1) != 0)
                    & (ins[:, 1:] != 0)).sum(1) + (ins[:, 0] != 0)
        multi[hm] = distinct >= 2
  n = max(len(h3), 1)
  for k in RADII_PX:
    res[f"purity_r{k}"] = float((d["trk"] <= k).sum() / n)
    res[f"fog_r{k}"] = float((d["fog"] <= k).sum() / n)
    res[f"chance_r{k}"] = float((d["chance"] <= k).sum() / n)
  res["multi"] = float(multi.sum() / n)

  vis = (~g["fog"]) & (g["col"] >= 0) & (g["col"] < w) & \
    (g["row"] >= 0) & (g["row"] < h) & (gs >= 0) & (gs < n_slices)
  vi = np.flatnonzero(vis)
  n_near = np.zeros(vi.size, int)
  for s, (tree, idx) in enumerate(band_trees(h3[:, :2], hz, n_slices)):
    gm = np.flatnonzero(gs[vi] == s)
    if tree is None or not gm.size:
      continue
    n_near[gm] = tree.query_ball_point(gxy[vi[gm]], COVER_R_PX,
                                       return_length=True)
  rec = n_near > 0
  cls = g["cls"][vi]
  for k, name in CLASS_NAMES.items():
    m = cls == k
    res[f"recall_{name}"] = float(rec[m].mean()) if m.any() else np.nan
  res["dup_med"] = float(np.median(n_near[rec])) if rec.any() else np.nan
  res.update(exclusive_scores(h3, g, near_g, vi, rec, n_slices))
  t = (cls >= 1) & (cls <= 4)
  xyz = np.column_stack([g["x_um"], g["y_um"], g["z_um"]])[vi]
  tt = track_table(g["instance"][vi][t], cls[t], xyz[t], rec[t])
  return res, tt


def exclusive_scores(h3, g, near_g, vi, rec, n_slices):
  """Merge-aware recall and depth error.

  Grains along one track sit closer than the optics resolve, so a
  one-to-one grain match is ill-defined; what a merge costs is support
  for a neighbouring track. Each hit is given to the track of its
  nearest grain only; a grain counts as found (xrecall) if a hit within
  COVER_R_PX and Z_TOL_SLICES was given to its own track. 'close' grains
  have a grain of another track within the same reach -- where merges
  happen. dz is the hit slice minus its nearest grain's continuous
  focal position, in slices, for hits whose nearest grain has no other
  track grain within reach (steep tracks make 'nearest' ambiguous)."""
  res = {}
  hz = hit_slices(h3, n_slices)
  have = near_g >= 0
  owner = np.where(have, g["instance"][np.maximum(near_g, 0)], 0)
  cls = g["cls"][vi]
  t = (cls >= 1) & (cls <= 4)
  ti = vi[t]
  gxy = np.column_stack([g["col"][ti], g["row"][ti]])
  gs = g["focus_slice"][ti].astype(int)
  inst = g["instance"][ti]
  xrec = np.zeros(ti.size, bool)
  close = np.zeros(ti.size, bool)
  # Track grains with no other track grain within reach
  alone = np.zeros(len(g["cls"]), bool)
  hit_bands = band_trees(h3[:, :2], hz, n_slices)
  grain_bands = band_trees(gxy, gs, n_slices)
  for s in range(n_slices):
    gm = np.flatnonzero(gs == s)
    if not gm.size:
      continue
    tree, idx = hit_bands[s]
    if tree is not None:
      dk, jk = tree.query(gxy[gm], k=MULTI_K,
                          distance_upper_bound=COVER_R_PX)
      ok = np.isfinite(dk)
      own = owner[idx[np.minimum(jk, len(idx) - 1)]]
      xrec[gm] = (ok & (own == inst[gm, None])).any(1)
    tree, idx = grain_bands[s]
    dk, jk = tree.query(gxy[gm], k=MULTI_K,
                        distance_upper_bound=COVER_R_PX)
    ok = np.isfinite(dk)
    other = inst[idx[np.minimum(jk, len(idx) - 1)]]
    close[gm] = (ok & (other != inst[gm, None])).any(1)
    alone[ti[gm]] = ok.sum(1) == 1
  # Depth error only where the nearest grain is unambiguous
  sel = have & alone[np.maximum(near_g, 0)]
  dz = h3[sel, 2] - g["slice"][near_g[sel]]
  res["dz_abs_med"] = float(np.median(np.abs(dz))) if dz.size else np.nan
  res["dz_bias"] = float(dz.mean()) if dz.size else np.nan
  res["dz_n"] = int(dz.size)
  for k, name in CLASS_NAMES.items():
    m = cls[t] == k
    if k <= 4 and m.any():
      res[f"xrecall_{name}"] = float(xrec[m].mean())
  res["close_frac"] = float(close.mean()) if close.size else np.nan
  if close.any():
    res["close_recall"] = float(rec[t][close].mean())
    res["close_xrecall"] = float(xrec[close].mean())
  return res


def track_table(inst, cls, xyz_um, cov):
  """Per-track grain recall and new gap along the track's main axis."""
  order = np.argsort(inst, kind="stable")
  inst = inst[order]
  starts = np.flatnonzero(np.r_[True, inst[1:] != inst[:-1]])
  ends = np.r_[starts[1:], len(inst)]
  xyz = xyz_um[order].astype(np.float64)
  cls, cv = cls[order], cov[order]
  rows = []
  for a, b in zip(starts, ends):
    if b - a < MIN_TRACK_GRAINS:
      continue
    p = xyz[a:b] - xyz[a:b].mean(0)
    axis = np.linalg.svd(p, full_matrices=False)[2][0]
    t = p @ axis
    o = np.argsort(t)
    t, k = t[o], cv[a:b][o]
    gap0 = np.diff(t).max()
    tk = t[k]
    if len(tk) > 1:
      gap = max(np.diff(tk).max(), tk[0] - t[0], t[-1] - tk[-1])
    else:
      gap = t[-1] - t[0]
    rows.append({"inst": int(inst[a]),
                 "cls": int(np.bincount(cls[a:b]).argmax()),
                 "n": int(b - a), "length_um": t[-1] - t[0],
                 "dip": float(abs(axis[2])),
                 "coverage": float(k.mean()),
                 "new_gap_um": float(gap - gap0)})
  return pd.DataFrame(rows)


def budget(h3):
  """Hits per graph-detector region: max and 90th percentile."""
  if not len(h3):
    return {"region_max": 0, "region_p90": 0.0}
  key = (h3[:, 0] // REGION_PX).astype(np.int64) * 1_000_000 + \
    (h3[:, 1] // REGION_PX).astype(np.int64) * 1000 + \
    (h3[:, 2] // REGION_Z).astype(np.int64)
  n = np.unique(key, return_counts=True)[1]
  return {"region_max": int(n.max()),
          "region_p90": float(np.percentile(n, 90))}


def collect_hits(reader, variants, clf, cell):
  """Hits (x, y, slice) and seconds per mask variant over the stack."""
  hits = {v: [] for v in variants}
  secs = {v: 0.0 for v in variants}
  for s in range(len(reader)):
    fog, masks, msecs = slice_masks(reader.read(s), variants, clf)
    for v in variants:
      t = time.time()
      hh = weighted_grid_hits(masks[v], fog, cell)
      secs[v] += time.time() - t + chain_seconds(v, msecs)
      hits[v].append(np.column_stack([hh[:, :2], np.full(len(hh), s)]))
  return {v: np.concatenate(hits[v]) for v in variants}, secs


def depth_offset(prof):
  """Sub-slice position of a depth maximum: least-squares parabola
  through the responses at slice offsets -FIT_HALF..FIT_HALF (one row
  per hit, NaN where the stack ends); 0 where fewer than three slices
  exist or the fit does not bend down."""
  k = np.arange(-FIT_HALF, FIT_HALF + 1, dtype=float)
  ok = np.isfinite(prof)
  y = np.where(ok, prof, 0.0)
  basis = np.stack([np.ones_like(k), k, k * k])          # (3, M)
  w = ok.astype(float)
  ata = np.einsum("nm,im,jm->nij", w, basis, basis)
  aty = np.einsum("nm,im->ni", w * y, basis)
  good = ok.sum(1) >= 3
  coef = np.zeros_like(aty)
  coef[good] = np.linalg.solve(ata[good], aty[good][..., None])[..., 0]
  b, c = coef[:, 1], coef[:, 2]
  with np.errstate(divide="ignore", invalid="ignore"):
    off = np.where(good & (c < 0), -b / (2.0 * c), 0.0)
  return np.clip(off, -MAX_SUBSLICE, MAX_SUBSLICE)


def hit_slices(h3, n_slices):
  """Nearest slice index of each hit (z may be sub-slice)."""
  return np.clip(np.rint(h3[:, 2]), 0, n_slices - 1).astype(int)


def dog_response(img):
  """Grain-scale band-pass of the fog-removed slice (grains positive)."""
  f = fog_remove(img).astype(np.float32)
  return cv2.GaussianBlur(f, (0, 0), DOG_SIGMA_IN_PX) - \
    cv2.GaussianBlur(f, (0, 0), DOG_SIGMA_OUT_PX)


def dog_hits(reader, k=None):
  """Hits from 2-D and 3-D local maxima of the DoG response."""
  k = DOG_K if k is None else k
  out = {"dog": [], "dog3d": [], "dog3dz": []}
  secs = {"dog": 0.0, "dog3d": 0.0, "dog3dz": 0.0}
  n = len(reader)
  win = {}
  for s in range(n + FIT_HALF):
    t = time.time()
    if s < n:
      r = dog_response(reader.read(s))
      med = np.median(r)
      thr = med + k * _MAD_TO_SIGMA * np.median(np.abs(r - med))
      mx = maximum_filter(r, size=DOG_PEAK_PX)
      win[s] = (r, mx, (r == mx) & (r > thr))
    dt = time.time() - t
    for v in out:
      secs[v] += dt
    c = s - FIT_HALF
    if c < 0:
      continue
    t = time.time()
    r, mx, peak = win[c]
    ys, xs = np.nonzero(peak)
    out["dog"].append(np.column_stack([xs, ys, np.full(xs.size, c)]))
    keep = np.ones(xs.size, bool)
    for nb in (c - 1, c + 1):
      if nb in win:
        keep &= r[ys, xs] >= win[nb][1][ys, xs]
    out["dog3d"].append(np.column_stack(
      [xs[keep], ys[keep], np.full(keep.sum(), c)]))
    secs["dog3d"] += time.time() - t
    xk, yk = xs[keep], ys[keep]
    prof = np.column_stack([
      win[c + o][0][yk, xk] if c + o in win else np.full(xk.size, np.nan)
      for o in range(-FIT_HALF, FIT_HALF + 1)])
    out["dog3dz"].append(np.column_stack([xk, yk,
                                          c + depth_offset(prof)]))
    secs["dog3dz"] += time.time() - t
    win.pop(c - FIT_HALF, None)
  return {v: np.concatenate(out[v]).astype(float) for v in out}, secs


def _line_kernels():
  """Zero-mean ridge kernels, one per direction."""
  half = int(_KERNEL_HALF_SIGMAS * RIDGE_SIGMA_ALONG_PX)
  y, x = np.mgrid[-half:half + 1, -half:half + 1].astype(np.float32)
  out = []
  for th in np.linspace(0, np.pi, RIDGE_ANGLES, endpoint=False):
    u = x * np.cos(th) + y * np.sin(th)
    v = -x * np.sin(th) + y * np.cos(th)
    vv = v * v / RIDGE_SIGMA_CROSS_PX ** 2
    k = (1 - vv) * np.exp(-u * u / (2 * RIDGE_SIGMA_ALONG_PX ** 2)
                          - vv / 2)
    k -= k.mean()
    out.append(k / np.abs(k).sum())
  return out


_LINE_KERNELS = _line_kernels()


def ridge_response(img):
  """Best oriented line response of the fog-removed slice."""
  f = fog_remove(img).astype(np.float32)
  return np.max([cv2.filter2D(f, -1, k) for k in _LINE_KERNELS], axis=0)


def line_mask(r, k=RIDGE_K):
  """Centre lines of the long structures above k robust sigmas."""
  med = np.median(r)
  m = r > med + k * _MAD_TO_SIGMA * np.median(np.abs(r - med))
  sk = skeletonize(remove_small_objects(m, RIDGE_MIN_AREA_PX))
  n, lab = cv2.connectedComponents(sk.astype(np.uint8))
  size = np.bincount(lab.ravel(), minlength=n)
  size[0] = 0
  return (size[lab] >= RIDGE_MIN_LEN_PX).astype(np.uint8) * 255


def ridge_hits(reader, cell, k=RIDGE_K):
  """Hits on line centres, every slice and at each line's best slice."""
  out = {"ridge": [], "ridge3d": []}
  secs = {"ridge": 0.0, "ridge3d": 0.0}
  n = len(reader)
  win = {}
  for s in range(n + 1):
    t = time.time()
    if s < n:
      r = ridge_response(reader.read(s))
      hh = weighted_grid_hits(line_mask(r, k), np.maximum(r, 0), cell)
      win[s] = (r, maximum_filter(r, size=3), hh)
    dt = time.time() - t
    secs["ridge"] += dt
    secs["ridge3d"] += dt
    c = s - 1
    if c < 0:
      continue
    t = time.time()
    r, _, hh = win[c]
    out["ridge"].append(np.column_stack([hh[:, :2], np.full(len(hh), c)]))
    ys = np.clip(np.rint(hh[:, 1]).astype(int), 0, r.shape[0] - 1)
    xs = np.clip(np.rint(hh[:, 0]).astype(int), 0, r.shape[1] - 1)
    keep = np.ones(len(hh), bool)
    for nb in (c - 1, c + 1):
      if nb in win:
        keep &= r[ys, xs] >= win[nb][1][ys, xs]
    out["ridge3d"].append(np.column_stack(
      [hh[keep, :2], np.full(keep.sum(), c)]))
    secs["ridge3d"] += time.time() - t
    win.pop(c - 1, None)
  return {v: np.concatenate(out[v]) for v in out}, secs


# --- GPU path (torch) -----------------------------------------------
# Same filters as dog_response / ridge_response / maximum_filter, run on
# the whole stack at once. Kept numerically close to the OpenCV path
# (reflect-101 borders, fog_remove's uint8 rounding and saturation), not
# bit-identical; module.device.default_device() decides, E07_DEVICE=cpu
# forces the CPU path.
_FOG_SIGMA_PX = 8.0       # what cv2 derives for the 51 px fog kernel
_FOG_RADIUS_PX = 25
_GPU_BATCH = 8            # slices per batch on the GPU
_GAUSS_RADIUS_SIGMAS = 4


def _gauss_kernel(sigma, radius, dev):
  import torch
  x = torch.arange(-radius, radius + 1, device=dev, dtype=torch.float32)
  k = torch.exp(-x * x / (2 * sigma * sigma))
  return k / k.sum()


def _blur(x, sigma, radius=None):
  """Separable Gaussian blur of (N, 1, H, W), reflect-101 borders."""
  import torch.nn.functional as F
  r = radius or int(round(_GAUSS_RADIUS_SIGMAS * sigma))
  k = _gauss_kernel(sigma, r, x.device)
  x = F.conv2d(F.pad(x, (r, r, 0, 0), mode="reflect"), k.view(1, 1, 1, -1))
  return F.conv2d(F.pad(x, (0, 0, r, r), mode="reflect"),
                  k.view(1, 1, -1, 1))


def _fog_gpu(imgs):
  """fog_remove on a (N, 1, H, W) uint8-valued float tensor."""
  b = _blur(imgs, _FOG_SIGMA_PX, _FOG_RADIUS_PX).round()
  return (b - imgs).clamp(min=0)


def _stack_responses(reader, dev, fn):
  """fn(fog batch) for every slice, as one (S, H, W) GPU tensor."""
  import torch
  out = []
  for a in range(0, len(reader), _GPU_BATCH):
    b = min(a + _GPU_BATCH, len(reader))
    imgs = torch.from_numpy(np.stack([reader.read(s) for s in range(a, b)])
                            ).to(dev, torch.float32).unsqueeze(1)
    out.append(fn(_fog_gpu(imgs))[:, 0])
  return torch.cat(out)


def _robust_thr(r, k):
  """Per-slice median + k robust sigmas of an (S, H, W) tensor."""
  flat = r.flatten(1)
  med = flat.median(dim=1).values
  mad = (flat - med[:, None]).abs().median(dim=1).values
  return (med + k * _MAD_TO_SIGMA * mad)[:, None, None]


def _neighbour_max(mx):
  """Per slice, the max of mx over the slices either side (or -inf)."""
  import torch
  pad = torch.full_like(mx[:1], -float("inf"))
  prev = torch.cat([pad, mx[:-1]])
  nxt = torch.cat([mx[1:], pad])
  return torch.maximum(prev, nxt)


def dog_hits_gpu(reader, dev, k=None):
  """dog_hits on the GPU."""
  k = DOG_K if k is None else k
  import torch
  import torch.nn.functional as F
  t = time.time()
  dog = lambda f: _blur(f, DOG_SIGMA_IN_PX) - _blur(f, DOG_SIGMA_OUT_PX)
  with torch.no_grad():
    r = _stack_responses(reader, dev, dog)
    mx = F.max_pool2d(r.unsqueeze(1), DOG_PEAK_PX, 1,
                      DOG_PEAK_PX // 2)[:, 0]
    peak = (r == mx) & (r > _robust_thr(r, k))
    keep = peak & (r >= _neighbour_max(mx))
    out = {}
    for v, m in (("dog", peak), ("dog3d", keep)):
      z, y, x = torch.nonzero(m, as_tuple=True)
      out[v] = torch.stack([x, y, z], 1).cpu().numpy().astype(float)
    # Neighbour responses; a missing neighbour (stack end) is replaced
    # by the centre, which leaves the slice unrefined
    last = r.shape[0] - 1
    nan = torch.tensor(float("nan"), device=r.device)
    prof = torch.stack([
      torch.where((z + o >= 0) & (z + o <= last),
                  r[(z + o).clamp(0, last), y, x], nan)
      for o in range(-FIT_HALF, FIT_HALF + 1)], 1)
    zf = z.cpu().numpy() + depth_offset(prof.cpu().numpy())
    out["dog3dz"] = np.column_stack([out["dog3d"][:, :2], zf])
  del r, mx, peak, keep
  torch.cuda.empty_cache()
  dt = time.time() - t
  return out, {"dog": dt, "dog3d": dt, "dog3dz": dt}


def ridge_hits_gpu(reader, cell, dev, k=RIDGE_K):
  """ridge_hits with the oriented filters on the GPU; thinning and
  sampling stay on the CPU."""
  import torch
  import torch.nn.functional as F
  t = time.time()
  w = torch.from_numpy(np.stack(_LINE_KERNELS)).to(dev, torch.float32)
  w = w.unsqueeze(1)
  half = w.shape[-1] // 2
  line = lambda f: F.conv2d(F.pad(f, (half,) * 4, mode="reflect"),
                            w).amax(1, keepdim=True)
  with torch.no_grad():
    r = _stack_responses(reader, dev, line)
    nb = _neighbour_max(F.max_pool2d(r.unsqueeze(1), 3, 1, 1)[:, 0])
    thr = _robust_thr(r, k)[:, 0, 0].cpu().numpy()
  out = {"ridge": [], "ridge3d": []}
  for s in range(r.shape[0]):
    rs = r[s].cpu().numpy()
    m = rs > thr[s]
    sk = skeletonize(remove_small_objects(m, RIDGE_MIN_AREA_PX))
    n, lab = cv2.connectedComponents(sk.astype(np.uint8))
    size = np.bincount(lab.ravel(), minlength=n)
    size[0] = 0
    mask = (size[lab] >= RIDGE_MIN_LEN_PX).astype(np.uint8) * 255
    hh = weighted_grid_hits(mask, np.maximum(rs, 0), cell)
    out["ridge"].append(np.column_stack([hh[:, :2], np.full(len(hh), s)]))
    ys = np.clip(np.rint(hh[:, 1]).astype(int), 0, rs.shape[0] - 1)
    xs = np.clip(np.rint(hh[:, 0]).astype(int), 0, rs.shape[1] - 1)
    keep = rs[ys, xs] >= nb[s].cpu().numpy()[ys, xs]
    out["ridge3d"].append(np.column_stack(
      [hh[keep, :2], np.full(keep.sum(), s)]))
  del r, nb
  torch.cuda.empty_cache()
  dt = time.time() - t
  return {v: np.concatenate(out[v]) for v in out}, {"ridge": dt,
                                                    "ridge3d": dt}


def _gpu_or_cpu(gpu_fn, cpu_fn):
  """Run on the GPU when there is one; fall back to the CPU when it is
  out of memory (several evaluations may share one card)."""
  dev = default_device()
  if dev:
    import torch
    try:
      return gpu_fn(dev)
    except (torch.OutOfMemoryError,
            getattr(torch, "AcceleratorError", torch.OutOfMemoryError)):
      torch.cuda.empty_cache()
      print("GPU out of memory; CPU path", file=sys.stderr, flush=True)
  return cpu_fn()


def merge_hits(a, b):
  """a plus the hits of b farther than COVER_R_PX from a (same slice)."""
  keep = np.ones(len(b), bool)
  for s in np.unique(b[:, 2]):
    ia, ib = a[:, 2] == s, np.flatnonzero(b[:, 2] == s)
    if ia.any() and ib.size:
      d = cKDTree(a[ia, :2]).query(b[ib, :2])[0]
      keep[ib] = d > COVER_R_PX
  return np.concatenate([a, b[keep]])


def focus_suppress(reader, h3):
  """Keep the hits whose smoothed darkness is at least the 3x3 maximum
  of the slices either side (each grain at its sharpest slice)."""
  f = np.stack([cv2.GaussianBlur(fog_remove(reader.read(s)).astype(
    np.float32), (0, 0), FOCUS_SIGMA_PX) for s in range(len(reader))])
  mx = maximum_filter(f, size=(1, 3, 3))
  ninf = np.full_like(mx[:1], -np.inf)
  nb = np.maximum(np.concatenate([ninf, mx[:-1]]),
                  np.concatenate([mx[1:], ninf]))
  z = h3[:, 2].astype(int)
  y = np.clip(np.rint(h3[:, 1]).astype(int), 0, f.shape[1] - 1)
  x = np.clip(np.rint(h3[:, 0]).astype(int), 0, f.shape[2] - 1)
  return h3[f[z, y, x] >= nb[z, y, x]]


def build_hits(reader, variants, clf, cell):
  """Hits and seconds for every requested variant on one stack."""
  masks = [v for v in variants if v in MASK_VARIANTS]
  masks += [ZSUP_VARIANTS[v] for v in variants if v in ZSUP_VARIANTS]
  masks = sorted(set(masks), key=MASK_VARIANTS.index)
  if "otsu_rand" in variants:
    masks = sorted(set(masks) | {"otsu", "classifier"},
                   key=MASK_VARIANTS.index)
  hits, secs = collect_hits(reader, masks, clf, cell)
  if any(v in DOG_VARIANTS or v == "dogridge" for v in variants):
    dh, ds = _gpu_or_cpu(lambda dev: dog_hits_gpu(reader, dev),
                         lambda: dog_hits(reader))
    hits.update(dh)
    secs.update(ds)
  if any(v in RIDGE_VARIANTS for v in variants):
    rh, rs = _gpu_or_cpu(lambda dev: ridge_hits_gpu(reader, cell, dev),
                         lambda: ridge_hits(reader, cell))
    hits.update(rh)
    secs.update(rs)
  if "dogridge" in variants:
    hits["dogridge"] = merge_hits(hits["dog3d"], hits["ridge3d"])
    secs["dogridge"] = secs["dog3d"] + secs["ridge3d"]
  for v in variants:
    if v in ZSUP_VARIANTS:
      t = time.time()
      hits[v] = focus_suppress(reader, hits[ZSUP_VARIANTS[v]])
      secs[v] = secs[ZSUP_VARIANTS[v]] + time.time() - t
  if "otsu_rand" in variants:
    rng = np.random.default_rng(SEED)
    o = hits["otsu"]
    keep = rng.choice(len(o), size=min(len(hits["classifier"]), len(o)),
                      replace=False)
    hits["otsu_rand"] = o[np.sort(keep)]
    secs["otsu_rand"] = secs["otsu"]
  return hits, secs


def score_row(h3, g, shape, n_slices):
  """Summary metrics and per-track table for one set of hits."""
  row, tt = grain_scores(h3, g, shape, n_slices)
  for name, sub in (("bg", tt[tt.cls == 4]), ("sig", tt[tt.cls < 4])):
    if len(sub):
      row[f"{name}_tracks"] = len(sub)
      row[f"{name}_lost"] = float((sub.coverage == 0).mean())
      row[f"{name}_cov_mean"] = float(sub.coverage.mean())
      row[f"{name}_cov_p10"] = float(sub.coverage.quantile(0.1))
      row[f"{name}_newgap_med_um"] = float(sub.new_gap_um.median())
  return row, tt


def evaluate(ev_dir, variants, clf, cell):
  """Score every variant; for an embedded event also the same variants
  on the background view alone (columns prefixed bgctl_), the support
  the signal grains would get from background hits by chance."""
  reader = load_spng(ev_dir / "image.json")
  shape = reader.read(0).shape[:2]
  g = dict(np.load(ev_dir / "grains.npz"))
  truth = json.loads((ev_dir / "truth.json").read_text())
  hits, secs = build_hits(reader, variants, clf, cell)
  bg_view = truth.get("background_view")
  bg_hits = None
  if bg_view and Path(bg_view).exists():
    bg_reader = load_spng(bg_view)
    if len(bg_reader) == len(reader):
      bg_hits, _ = build_hits(bg_reader, variants, clf, cell)
  summary, tracks = [], []
  for v in variants:
    h3 = hits[v]
    row = {"event": ev_dir.name, "variant": v, "n_hits": len(h3),
           "seconds": round(secs[v], 1), **budget(h3)}
    res, tt = score_row(h3, g, shape, len(reader))
    row.update(res)
    if bg_hits is not None:
      res, tb = score_row(bg_hits[v], g, shape, len(reader))
      row.update({f"bgctl_{k}": x for k, x in res.items()
                  if k.startswith(("recall_", "sig_"))})
      tt = tt.merge(tb[["inst", "coverage"]].rename(
        columns={"coverage": "bgctl_coverage"}), on="inst", how="left")
    tt.insert(0, "variant", v)
    tt.insert(0, "event", ev_dir.name)
    tracks.append(tt)
    summary.append(row)
  return pd.DataFrame(summary), pd.concat(tracks)


def main() -> int:
  global DOG_K
  ap = argparse.ArgumentParser()
  ap.add_argument("events", nargs="+", type=Path)
  ap.add_argument("--out", type=Path,
                  default=Path("results/pointcloud_eval"))
  ap.add_argument("--variants",
                  default=",".join(MASK_VARIANTS + ("otsu_rand",)
                                   + DOG_VARIANTS + RIDGE_VARIANTS))
  ap.add_argument("--cell", type=int, default=_GRAPH_CELL_PX)
  ap.add_argument("--tag", default="", help="prefix for output files")
  ap.add_argument("--dog-k", type=float, default=DOG_K,
                  help="DoG threshold in robust sigmas")
  args = ap.parse_args()
  DOG_K = args.dog_k
  variants = tuple(args.variants.split(","))
  clf = train_classifier(*build_training_set(_LABELS_DIR))
  args.out.mkdir(parents=True, exist_ok=True)
  for ev in args.events:
    name = f"{args.tag}{ev.parent.name}__{ev.name}"
    out = args.out / f"{name}_summary.csv"
    if out.exists():
      continue
    summ, tracks = evaluate(ev, variants, clf, args.cell)
    tracks.to_csv(args.out / f"{name}_tracks.csv", index=False)
    summ.to_csv(out, index=False)
    print(summ.to_string(index=False), flush=True)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
