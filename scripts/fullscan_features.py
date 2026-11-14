"""Ranking features for every full-scan union candidate, in the schema of
candidate_features.py, so the frozen review rankers of
e07-g4-hypernuclei (./run.py candscore apply MODEL IN OUT) score them.

Per view, A rows are the union's A candidates; B' features use the
view's full B' list (results/fullscan_bprime/<view>.csv, all branch
points, as on the synthetic sets: n_bp_20px and dist_other_um count
every point), and only the union's B' rows (the 770 darkest) are kept,
matched by position. union_row is the row index in union.parquet.

  python scripts/fullscan_features.py [--procs N]
    # -> results/fullscan_union/features.parquet
"""
import argparse
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import candidate_features as cf  # noqa: E402
from fullscan_bprime import OUT as BPRIME, VIEWS  # noqa: E402
from fullscan_union import OUT as UNION  # noqa: E402
from module.reader import load_spng  # noqa: E402

OUT = UNION.parent / "features.parquet"
PROCS = 8
MATCH_PX = 1e-3
UM_PER_MM = 1000.0


def one(job):
  view, a, ub = job
  b = pd.read_csv(BPRIME / f"{view}.csv")
  reader = load_spng(VIEWS / f"{view}.json")
  stack, z = reader.read_stack(), reader.z_positions()
  fa = cf.view_features(a, stack, z, "z_best")
  fa = pd.concat([a[cf.A_COLS].reset_index(drop=True), fa], axis=1)
  fa["z_span_um"] = ((a.z_max - a.z_min).abs() * UM_PER_MM).to_numpy()
  fa["dist_other_um"] = cf.nearest_other(a, b)
  fa["union_row"] = a.index.to_numpy()
  fb = cf.view_features(b, stack, z, "z_mean")
  fb["mult"] = b.n_tracks_max.to_numpy()
  xy = b[["vx_px", "vy_px"]].to_numpy()
  fb["n_bp_20px"] = [len(n) - 1 for n in
                     cKDTree(xy).query_ball_point(xy, cf.NEIGH_PX)]
  fb["dist_other_um"] = cf.nearest_other(b, a)
  d, j = cKDTree(xy).query(ub[["vx_px", "vy_px"]].to_numpy())
  if (d > MATCH_PX).any():
    raise RuntimeError(f"{view}: {int((d > MATCH_PX).sum())} union B' "
                       "rows not in the B' list")
  fb = fb.iloc[j].reset_index(drop=True)
  fb["union_row"] = ub.index.to_numpy()
  return pd.concat([fa.assign(source="A"), fb.assign(source="Bprime")],
                   ignore_index=True).assign(view=view)


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("--procs", type=int, default=PROCS)
  ap.add_argument("--first", type=int, default=0)
  ap.add_argument("--last", type=int, default=None)
  ap.add_argument("--out", type=Path, default=OUT)
  args = ap.parse_args()
  u = pd.read_parquet(UNION)
  views = sorted(u.view.unique())[args.first:args.last]
  g = dict(list(u.groupby("view")))
  jobs = [(v, g[v][g[v].source == "A"], g[v][g[v].source == "Bprime"])
          for v in views]
  with Pool(args.procs) as p:
    out = []
    for i, df in enumerate(p.imap(one, jobs, chunksize=1), 1):
      out.append(df)
      if i % 100 == 0 or i == len(jobs):
        print(f"{i}/{len(jobs)} views", flush=True)
  df = pd.concat(out, ignore_index=True)
  key = ["view", "source", "union_row"]
  df[key + [c for c in df.columns if c not in key]].to_parquet(args.out)
  print(f"wrote {args.out} ({len(df)} rows)")


if __name__ == "__main__":
  main()
