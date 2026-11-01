"""Sanity summary of the full-scan union (fullscan_union.py output).

  python scripts/fullscan_union_summary.py [--union FILE] [--views DIR]

Prints, and writes next to the union as summary.txt: the view count
against the image views, per-view A and B' counts, views with fewer B'
rows than TOP_K, non-finite or out-of-image positions, and how many B'
rows lie within NEAR_PX (xy) of an A candidate of the same view (the
merge distance of the A catalogue), i.e. how much of B' is new, next
to the same fraction for uniform random points (chance level).
A vertices are line crossings and may sit slightly off the image.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from fullscan_bprime import VIEWS  # noqa: E402
from fullscan_union import OUT  # noqa: E402
from module.pipeline.union import TOP_K  # noqa: E402

NEAR_PX = 50.0
IMAGE_PX = 2048
POS = ["vx_px", "vy_px", "z_mean"]
RAND_SEED = 0


def near_frac(g):
  a = g[g.source == "A"][["vx_px", "vy_px"]].to_numpy()
  b = g[g.source == "Bprime"][["vx_px", "vy_px"]].to_numpy()
  if not len(b):
    return 0, 0, 0
  if not len(a):
    return 0, len(b), 0
  tree = cKDTree(a)
  d, _ = tree.query(b)
  r = np.random.default_rng(RAND_SEED).uniform(0, IMAGE_PX, b.shape)
  dr, _ = tree.query(r)
  return int((d <= NEAR_PX).sum()), len(b), int((dr <= NEAR_PX).sum())


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("--union", type=Path, default=OUT)
  ap.add_argument("--views", type=Path, default=VIEWS)
  args = ap.parse_args()

  u = pd.read_parquet(args.union)
  n_img = len(list(args.views.glob("*.json")))
  cnt = u.groupby(["view", "source"]).size().unstack(fill_value=0)
  for s in ("A", "Bprime"):
    if s not in cnt:
      cnt[s] = 0
  bad = ~np.isfinite(u[POS].to_numpy()).all(axis=1)
  out = ((u.vx_px < 0) | (u.vx_px >= IMAGE_PX)
         | (u.vy_px < 0) | (u.vy_px >= IMAGE_PX))
  near = np.array([near_frac(g) for _, g in u.groupby("view")])
  lines = [
    f"union: {args.union}",
    f"views: {len(cnt)} of {n_img} image views",
    f"rows: A {int(cnt.A.sum())}, B' {int(cnt.Bprime.sum())}",
    "A per view: min {} median {:.0f} max {}".format(
      cnt.A.min(), cnt.A.median(), cnt.A.max()),
    "B' per view: min {} median {:.0f} max {}".format(
      cnt.Bprime.min(), cnt.Bprime.median(), cnt.Bprime.max()),
    f"views with B' < {TOP_K}: {int((cnt.Bprime < TOP_K).sum())}",
    f"views with no A: {int((cnt.A == 0).sum())}",
    f"non-finite positions: {int(bad.sum())}",
    "outside the image: A {}, B' {}".format(
      int((out & (u.source == "A")).sum()),
      int((out & (u.source == "Bprime")).sum())),
    f"B' within {NEAR_PX:.0f} px of an A candidate: "
    f"{near[:, 0].sum()} of {near[:, 1].sum()} "
    f"({near[:, 0].sum() / max(near[:, 1].sum(), 1):.1%}; "
    f"random points {near[:, 2].sum() / max(near[:, 1].sum(), 1):.1%})",
  ]
  text = "\n".join(lines) + "\n"
  print(text, end="")
  (args.union.parent / "summary.txt").write_text(text)


if __name__ == "__main__":
  main()
