"""Per-candidate features for the ranking study (e07-g4-hypernuclei owns
the scorer: budget curves, labels, grouped CV, ranker).

For each event of a union_inputs.py set, every method-A candidate and
every B' branch point (all of them, before the top-770 darkness cut)
gets one row keyed by (event, source, cand_id), cand_id being the
0-based row index of the candidate within its event in the production
CSV of that source. Features use only the image and the candidates,
never the truth:

  all       darkness (module.pipeline.union.local_darkness at the
            candidate's slice; A uses z_best), dark_rank_view (1 =
            darkest among the view's candidates of the same source),
            edge_px (distance to the nearest image border), slice
  A         n_tracks_max, n_slices, mean_intens, angle_spread_best,
            angle_spread_max, z_span_um (stage)
  B'        mult (branch multiplicity), n_bp_20px (other B' points
            within NEIGH_PX in xy)
  cross     dist_other_um: xy distance (um, PX_UM) to the nearest
            candidate of the other source within DZ_STAGE_UM in stage z,
            inf if none

  python scripts/candidate_features.py v25_embed_nagara_dz4
    # -> results/sim_eval/v25_embed_nagara_dz4_features.parquet
  python scripts/candidate_features.py v19_bgonly_nagara_dz4 \
    --truth-set v25_embed_nagara_dz4   # real views before embedding

The image of an event is the `view` of <set>_events.csv; sets without
that file (older real-view runs) take each event's truth.json
background_view from --truth-set.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from module.pipeline.union import local_darkness, stage_to_slice  # noqa
from module.reader import load_spng  # noqa: E402

IMAGES = REPO.parent / "e07-g4-hypernuclei/data/images"
SIM_EVAL = REPO / "results/sim_eval"
PX_UM = 0.507
NEIGH_PX = 20.0
DZ_STAGE_UM = 15.0
UM_PER_MM = 1000.0
A_COLS = ["n_tracks_max", "n_slices", "mean_intens", "angle_spread_best",
          "angle_spread_max"]


def view_features(df, stack, z, z_col):
  sl = stage_to_slice(df[z_col].to_numpy(), z)
  xy = df[["vx_px", "vy_px"]].to_numpy()
  dark = local_darkness(stack, xy, sl)
  h, w = stack.shape[1:]
  edge = np.minimum.reduce([xy[:, 0], xy[:, 1], w - 1 - xy[:, 0],
                            h - 1 - xy[:, 1]])
  rank = (-dark).argsort(kind="stable").argsort() + 1
  return pd.DataFrame({"darkness": dark, "dark_rank_view": rank,
                       "edge_px": edge, "slice": sl})


def nearest_other(src, dst):
  """xy distance (um) from each src to the nearest dst within
  DZ_STAGE_UM in stage z."""
  out = np.full(len(src), np.inf)
  if not len(src) or not len(dst):
    return out
  tree = cKDTree(dst[["vx_px", "vy_px"]].to_numpy())
  zd = dst.z_mean.to_numpy() * UM_PER_MM
  d, j = tree.query(src[["vx_px", "vy_px"]].to_numpy(), k=16)
  ok = j < len(dst)
  jj = np.where(ok, j, 0)
  zs = src.z_mean.to_numpy()[:, None] * UM_PER_MM
  ok &= np.abs(zd[jj] - zs) <= DZ_STAGE_UM
  d = np.where(ok, d, np.inf).min(axis=1)
  return d * PX_UM


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("dataset")
  ap.add_argument("--out", type=Path, default=None)
  ap.add_argument("--truth-set", default=None,
                  help="image set whose truth.json background_view "
                  "gives each event's view (sets without _events.csv)")
  args = ap.parse_args()
  fa = pd.read_csv(SIM_EVAL / f"{args.dataset}_methodA_production.csv")
  fb = pd.read_csv(SIM_EVAL / f"{args.dataset}_bprime.csv")
  f_ev = SIM_EVAL / f"{args.dataset}_events.csv"
  if f_ev.exists():
    e = pd.read_csv(f_ev)
    views = dict(zip(e.event, e.view))
  elif args.truth_set:
    views = {d.name: json.loads((d / "truth.json").read_text())
             ["background_view"]
             for d in sorted((IMAGES / args.truth_set).glob("ev*"))}
  else:
    sys.exit(f"no {f_ev.name}; give --truth-set")
  rows = []
  for ev, view in views.items():
    a = fa[fa.event == ev].reset_index(drop=True)
    b = fb[fb.event == ev].reset_index(drop=True)
    reader = load_spng(Path(view))
    stack, z = reader.read_stack(), reader.z_positions()
    if len(a):
      fa_ = view_features(a, stack, z, "z_best")
      fa_ = pd.concat([a[A_COLS], fa_], axis=1)
      fa_["z_span_um"] = (a.z_max - a.z_min).abs() * UM_PER_MM
      fa_["dist_other_um"] = nearest_other(a, b)
      rows.append(fa_.assign(event=ev, source="A", cand_id=a.index))
    if len(b):
      fb_ = view_features(b, stack, z, "z_mean")
      fb_["mult"] = b.n_tracks_max.to_numpy()
      xy = b[["vx_px", "vy_px"]].to_numpy()
      fb_["n_bp_20px"] = [len(n) - 1 for n in
                          cKDTree(xy).query_ball_point(xy, NEIGH_PX)]
      fb_["dist_other_um"] = nearest_other(b, a)
      rows.append(fb_.assign(event=ev, source="Bprime", cand_id=b.index))
    print(f"{ev}: A {len(a)}, B' {len(b)}", flush=True)
  out = args.out or SIM_EVAL / f"{args.dataset}_features.parquet"
  df = pd.concat(rows, ignore_index=True)
  key = ["event", "source", "cand_id"]
  df[key + [c for c in df.columns if c not in key]].to_parquet(out)
  print(f"wrote {out} ({len(df)} rows)")


if __name__ == "__main__":
  main()
