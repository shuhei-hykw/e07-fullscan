"""Does the A + darkest-B' union (module/pipeline/union.py) hold the
confirmed vertex of each specials event, and from which source?

No new detector runs: A is the merged production table dumped by
rank_specials.py --dump-merged, B' the production-variant branch
points of graphdet_specials.py (P0, cell 6, classifier, z 3.8, an
80-slice window around the clicked slice). Darkness comes from the full
stack, as in the full scan.

A candidate matches when it lies within TOL px in xy of the click and
the clicked depth falls in its z span +- the truth file's Z tolerance
(rank_specials.rank_of_truth). The click is only good to +-50-100 px,
so several xy tolerances are reported. For each event and tolerance:
the best A rank (n_tracks_max descending), the best dark_rank among the
union's B' rows, and the best dark_rank among all B' points (before the
top-k cut; ranks past k mean the darkness order dropped it).

  python scripts/union_specials.py [--out results/union_specials.csv]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import rank_specials as rs  # noqa: E402
from module.pipeline.union import (TOP_K, local_darkness,  # noqa: E402
                                   stage_to_slice, top_k, union_candidates)
from module.reader import load_spng  # noqa: E402

A_DIR = REPO / "results/specials_merged"
B_DIR = REPO / "results/graphdet_specials_real"
OUT = REPO / "results/union_specials.csv"
TOLS_PX = (200, 100, 50)


def matches(df, gt, tol_xy, tol_z_mm, true_z):
  d = np.hypot(df["vx_px"] - gt["vx"], df["vy_px"] - gt["vy"])
  return ((d <= tol_xy) & (df["z_min"] - tol_z_mm <= true_z)
          & (true_z <= df["z_max"] + tol_z_mm)).to_numpy()


def best(rank, ok):
  return int(rank[ok].min()) + 1 if ok.any() else None


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("--out", type=Path, default=OUT)
  args = ap.parse_args()

  gt_all = json.loads(rs._GT_PATH.read_text())
  tol_z_mm = float(gt_all["tolerance_z_um"]) / rs._UM_PER_MM
  rows = []
  for ev, gt in gt_all["events"].items():
    path = rs._SPECIALS / ev / "image.json"
    a = pd.read_parquet(A_DIR / f"{ev}__production.parquet")
    p = pd.read_csv(B_DIR / f"{ev}_points.csv")
    b = pd.DataFrame({"vx_px": p.vx_px, "vy_px": p.vy_px,
                      "z_mean": p.z_mm, "z_min": p.z_mm, "z_max": p.z_mm,
                      "n_tracks_max": p.mult})
    reader = load_spng(path)
    stack, z = reader.read_stack(), reader.z_positions()
    true_z = rs.true_z_mm(path, gt)
    u = union_candidates(a, b, stack, z)
    ua = u[u.source == "A"].reset_index(drop=True)
    ub = u[u.source == "Bprime"].reset_index(drop=True)
    a_rank = (-ua.n_tracks_max).rank(method="first").to_numpy() - 1
    dark = local_darkness(stack, b[["vx_px", "vy_px"]].to_numpy(),
                          stage_to_slice(b.z_mean.to_numpy(), z))
    all_rank = np.empty(len(b), int)
    all_rank[top_k(dark, len(b))] = np.arange(len(b))
    for tol in TOLS_PX:
      ok_a = matches(ua, gt, tol, tol_z_mm, true_z)
      ok_u = matches(ub, gt, tol, tol_z_mm, true_z)
      ok_b = matches(b, gt, tol, tol_z_mm, true_z)
      r = {"event": ev, "plate": "E07" if ev in rs._E07 else "E373",
           "tol_px": tol, "n_a": len(ua), "n_b_all": len(b),
           "a_rank": best(a_rank, ok_a),
           "b_union_rank": best(ub.dark_rank.to_numpy(), ok_u),
           "b_all_rank": best(all_rank, ok_b),
           "n_b_match": int(ok_b.sum())}
      r["union_hit"] = r["a_rank"] is not None or r["b_union_rank"] is not None
      rows.append(r)
      print(r, flush=True)
  out = pd.DataFrame(rows)
  out.to_csv(args.out, index=False)
  for tol in TOLS_PX:
    t = out[out.tol_px == tol]
    print(f"{tol} px: A {t.a_rank.notna().sum()}/{len(t)}, "
          f"B' top-{TOP_K} {t.b_union_rank.notna().sum()}, "
          f"union {int(t.union_hit.sum())}, "
          f"B' only {int((t.a_rank.isna() & t.b_union_rank.notna()).sum())}")


if __name__ == "__main__":
  main()
