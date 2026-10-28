"""Score saved graphdet polylines against truth.json track polylines, and
optionally apply the placement gate between two variants.

usage:
  rescore_truth_polylines.py DATASET_DIR RUN_DIR [RUN_DIR ...]
      [--near-z 4 1.5] [--out tracks.csv] [--compare BASE CAND]

RUN_DIR holds graphdet_pointcloud.py outputs (<set>__<ev>__<tag>.json
and _polys.npz). Polylines are read from the first RUN_DIR; json timing
and memory are read from every RUN_DIR (timing repetitions).

Each charged truth track with >= 2 samples inside the stack is sampled
every STEP_UM of physical arc length (pixel_um across, physical_dz_um x
shrink along z). A sample is covered by a polyline when a polyline
sample (every STEP_PX px) lies within NEAR_PX in x/y and NEAR_Z slices
in z. Per track: union coverage, best single-polyline coverage, and
frag50 (fewest polylines covering half the samples, greedy). A track
is good when best >= GOOD, lost when union == 0. Strata: physical
length < SHORT_UM and >= SHORT_UM.

--compare applies the evalA placement gate (analysis-note 2026-10-28
evalA freeze entry): the first --near-z is primary, the second the
guardrail. It first checks that every event has one run per RUN_DIR
and variant, that both variants saw the same truth tracks, and that
the repetitions' polylines are identical. Exit 0 PASS, 1 FAIL, 2
invalid (incomplete or inconsistent runs).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.graphdet.support import sample  # noqa: E402
from module.reader import load_spng  # noqa: E402

NEAR_PX = 3.0
STEP_UM = 0.5
STEP_PX = 0.5
GOOD = 0.5
SHORT_UM = 15.0
OFFSET = 1  # polylines are saved in 1-based export coordinates

# Gate margins (frozen with the evalA criteria)
POOLED_GOOD_MARGIN = 3        # tracks, primary tolerance
STRATUM_RATE_MARGIN = 0.05    # good-rate points, both strata, primary
GUARD_POOLED_MARGIN = 3       # tracks, guardrail tolerance
GUARD_LONG_RATE_MARGIN = 0.05  # long-stratum good-rate points, guardrail
OFFSIG_MEDIAN_MAX = 0.70      # paired cand/base off-signal length
OFFSIG_VIEW_MAX = 1.0
TIME_MEDIAN_MAX = 1.0         # paired cand/base end-to-end seconds


def truth_paths(truth, shape, n):
  """Per charged track: (id, samples (col, row, slice), length um)."""
  um = np.array([truth["pixel_um"], truth["pixel_um"],
                 truth["physical_dz_um"] * truth["shrink"]])
  out = []
  for t in truth["tracks"]:
    pl = np.array(t.get("polyline") or [], float)
    if t.get("charge", 0) == 0 or len(pl) < 2:
      continue
    s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(pl, axis=0) * um,
                                             axis=1))]
    if s[-1] <= 0:
      continue
    at = np.r_[np.arange(0.0, s[-1], STEP_UM), s[-1]]
    p = np.column_stack([np.interp(at, s, pl[:, c]) for c in range(3)])
    ok = ((p[:, 0] >= 0) & (p[:, 0] < shape[1]) & (p[:, 1] >= 0)
          & (p[:, 1] < shape[0]) & (p[:, 2] >= 0) & (p[:, 2] <= n - 1))
    if ok.sum() < 2:
      continue
    out.append((t["id"], p[ok], s[-1]))
  return out


def frag50(cov, n):
  """Fewest polylines (greedy) covering GOOD of the samples; inf if
  unreachable."""
  left, got, k = [set(c) for c in cov], 0, 0
  while got < GOOD * n:
    tally = {}
    for c in left:
      for i in c:
        tally[i] = tally.get(i, 0) + 1
    if not tally:
      return np.inf
    i = max(tally, key=tally.get)
    k += 1
    hit = [j for j, c in enumerate(left) if i in c]
    got += len(hit)
    for j in hit:
      left[j] = set()
  return k


def load_polys(f):
  d = np.load(f)
  if len(d["n"]) == 0:
    return []
  return np.split(d["xyz"] - OFFSET, np.cumsum(d["n"])[:-1])


def score_file(f, ds, near_z):
  polys = load_polys(f)
  # Scale z so the x/y-by-z box fits inside one ball query
  sc = np.array([1.0, 1.0, NEAR_PX / near_z])
  if polys:
    pts, pid = sample(polys, 1.0, STEP_PX)
  else:  # no polylines: every track is lost
    pts, pid = np.zeros((0, 3)), np.zeros(0, int)
  tree = cKDTree(pts * sc)
  ev = f.name.split("__")[1]
  truth = json.loads((ds / ev / "truth.json").read_text())
  rd = load_spng(ds / ev / "image.json")
  rows = []
  for tid, p, length in truth_paths(truth, rd.read(0).shape[:2], len(rd)):
    cov = []
    for q, h in zip(p, tree.query_ball_point(p * sc, NEAR_PX * np.sqrt(2))):
      h = np.asarray(h, int)
      ok = ((np.hypot(*(pts[h, :2] - q[:2]).T) <= NEAR_PX)
            & (np.abs(pts[h, 2] - q[2]) <= near_z))
      cov.append(set(pid[h[ok]].tolist()))
    n = len(p)
    cnt = {}
    for c in cov:
      for i in c:
        cnt[i] = cnt.get(i, 0) + 1
    rows.append(dict(event=ev, tid=tid, len_um=length,
                     union=sum(bool(c) for c in cov) / n,
                     best=max(cnt.values()) / n if cnt else 0.0,
                     frag50=frag50(cov, n)))
  return rows


def runs(run_dir):
  out = []
  for f in sorted(run_dir.glob("*.json")):
    r = json.loads(f.read_text())
    out.append(dict(event=r["event"], variant=r["variant"],
                    total_s=r["total_s"], rss=r["rss_tree_peak_mb"],
                    offsig=r["fake_len_px"]))
  return pd.DataFrame(out)


def gate(t, js, base, cand, zs):
  checks = []
  for z in zs:
    s = t[t.near_z == z]
    g = s.pivot_table(index=["event", "tid"], columns="variant",
                      values="good", aggfunc="first")
    short = s.groupby(["event", "tid"]).short.first()
    pooled = {v: int(g[v].sum()) for v in (base, cand)}
    lost = {v: int(s[(s.variant == v)].union.eq(0).sum())
            for v in (base, cand)}
    rate = {(k, v): g[v][short == k].mean()
            for k in (True, False) for v in (base, cand)}
    print(f"near_z {z}: tracks {len(g)} (short {int(short.sum())}), "
          f"good {pooled}, lost {lost}")
    for k in (True, False):
      print(f"  {'short' if k else 'long'}: good rate "
            f"{base} {rate[k, base]:.3f}, {cand} {rate[k, cand]:.3f}")
    if z == zs[0]:
      checks += [
        ("pooled good >= base - 3",
         pooled[cand] >= pooled[base] - POOLED_GOOD_MARGIN),
        ("lost <= base", lost[cand] <= lost[base])]
      checks += [(f"{'short' if k else 'long'} rate >= base - 0.05",
                  rate[k, cand] >= rate[k, base] - STRATUM_RATE_MARGIN)
                 for k in (True, False)]
    else:
      checks += [
        ("guard pooled good >= base - 3",
         pooled[cand] >= pooled[base] - GUARD_POOLED_MARGIN),
        ("guard long rate >= base - 0.05",
         rate[False, cand] >= rate[False, base] - GUARD_LONG_RATE_MARGIN)]
  m = js.groupby(["event", "variant"]).agg(
    t=("total_s", "mean"), off=("offsig", "first")).unstack("variant")
  off = m["off"][cand] / m["off"][base]
  tim = m["t"][cand] / m["t"][base]
  rss = js.groupby("variant").rss.max()
  print(f"off-signal ratio median {off.median():.3f} max {off.max():.3f}; "
        f"time ratio median {tim.median():.3f}; "
        f"RSS max {rss[base]:.0f} vs {rss[cand]:.0f} MB; "
        f"runs per variant {js.variant.value_counts().to_dict()}")
  checks += [("off-signal median <= 0.70", off.median() <= OFFSIG_MEDIAN_MAX),
             ("off-signal every view <= 1.0", off.max() <= OFFSIG_VIEW_MAX),
             ("time median ratio <= 1.0", tim.median() <= TIME_MEDIAN_MAX),
             ("RSS max <= base max", rss[cand] <= rss[base])]
  for name, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
  ok = all(ok for _, ok in checks)
  print("GATE", "PASS" if ok else "FAIL")
  return ok


def complete(t, js, run_dirs, base, cand, n_events):
  """Refuse to judge unless every run is present once, both variants saw
  the same truth tracks, numbers are finite, and the repetitions'
  polylines are identical."""
  bad = []
  ev = sorted(js.event.unique())
  if len(ev) != n_events:
    bad.append(f"{len(ev)} events in the runs, expected {n_events}")
  want = len(run_dirs)
  cnt = js.groupby(["event", "variant"]).size()
  for v in (base, cand):
    for e in ev:
      if cnt.get((e, v), 0) != want:
        bad.append(f"{e} {v}: {cnt.get((e, v), 0)} runs, expected {want}")
  if not np.isfinite(js[["total_s", "rss", "offsig"]].to_numpy()).all():
    bad.append("non-finite timing/memory/off-signal value")
  keys = {v: set(map(tuple, t[t.variant == v][["event", "tid"]]
                     .drop_duplicates().to_numpy())) for v in (base, cand)}
  if keys[base] != keys[cand]:
    bad.append("truth track sets differ between variants")
  for f in sorted(run_dirs[0].glob("*_polys.npz")):
    a = np.load(f)
    for d in run_dirs[1:]:
      g = d / f.name
      if not g.exists():
        bad.append(f"missing {g}")
        continue
      b = np.load(g)
      if not (np.array_equal(a["n"], b["n"])
              and np.array_equal(a["xyz"], b["xyz"])):
        bad.append(f"polylines differ between repetitions: {f.name}")
  for b in bad:
    print("INVALID:", b)
  return not bad


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("dataset", type=Path)
  ap.add_argument("run_dirs", type=Path, nargs="+")
  ap.add_argument("--near-z", type=float, nargs="+", default=[4.0, 1.5])
  ap.add_argument("--out", type=Path, default=None)
  ap.add_argument("--compare", nargs=2, metavar=("BASE", "CAND"))
  ap.add_argument("--n-events", type=int, default=None,
                  help="with --compare: events every run set must have")
  args = ap.parse_args()

  rows = []
  for f in sorted(args.run_dirs[0].glob("*_polys.npz")):
    tag = f.name[:-len("_polys.npz")].split("__")[2]
    for z in args.near_z:
      rows += [dict(r, variant=tag, near_z=z)
               for r in score_file(f, args.dataset, z)]
  t = pd.DataFrame(rows)
  t["short"] = t.len_um < SHORT_UM
  t["good"] = t.best >= GOOD
  if args.out:
    t.to_csv(args.out, index=False)
  for k, g in t.groupby(["near_z", "variant", "short"]):
    print(k, len(g), "good", int(g.good.sum()),
          "lost", int(g.union.eq(0).sum()),
          f"union {g.union.mean():.3f} best {g.best.mean():.3f} "
          f"frag50_med {g.frag50.median()}")
  if args.compare:
    js = pd.concat([runs(d) for d in args.run_dirs])
    js = js[js.variant.isin(args.compare)]
    n_ev = args.n_events or len(list(args.dataset.glob("ev*")))
    if not complete(t, js, args.run_dirs, *args.compare, n_ev):
      return 2
    return 0 if gate(t, js, *args.compare, args.near_z) else 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
