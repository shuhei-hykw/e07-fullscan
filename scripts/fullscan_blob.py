"""Blob features (peer module e07-g4-hypernuclei module/blobfeat.py,
ac46411) for every union candidate of the real full scan: half-width,
area and fill of the dark component touching the candidate in the
minimum projection over +-3 slices. A grain track is 1-2 px thick;
v26 capture points are <= 5 px.

The candidate slice is the nearest stage z to z_best (A) or z_mean
(B'), as in fullscan_features.py. The peer's package is imported as
is, so this script must not import this repo's `module` package.

  python scripts/fullscan_blob.py [--procs N]
  # -> results/fullscan_union/blob.parquet
"""
import argparse
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
PEER = REPO.parent / "e07-g4-hypernuclei"
sys.path.insert(0, str(PEER))
from module import blobfeat as bf  # noqa: E402
from module import imagestats as st  # noqa: E402

DIR = REPO / "results/fullscan_union"
UNION = DIR / "union.parquet"
OUT = DIR / "blob.parquet"
VIEWS = (REPO / "fullscan-image/E07/MOD108/PL12/tohoku-v1/AREA00"
         / "IMAGE00_AREA00")
PROCS = 12
UM_PER_MM = 1000.0


def one(job):
  view, g = job
  img = VIEWS / f"{view}.json"
  stack = np.array(st.read_stack(img))
  meta = pd.read_json(img, typ="series")
  zs = np.array([float(i["z"]) for i in meta["Images"]])
  get = bf.detection_maps(stack)
  z = np.where(g.source == "A", g.z_best, g.z_mean).astype(float)
  k = np.abs(z[:, None] - zs[None]).argmin(axis=1)
  rows = [bf.blob(get(int(kk)), x, y)
          for kk, x, y in zip(k, g.vx_px, g.vy_px)]
  out = pd.DataFrame(rows, columns=["blob_thick_px", "blob_area_px",
                                    "blob_fill"])
  out.insert(0, "union_row", g.index.to_numpy())
  return out


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("--procs", type=int, default=PROCS)
  ap.add_argument("--views", type=int, default=None,
                  help="first N views only (test)")
  args = ap.parse_args()
  u = pd.read_parquet(UNION, columns=["view", "source", "vx_px", "vy_px",
                                      "z_best", "z_mean"])
  jobs = list(u.groupby("view", sort=True))[:args.views]
  parts = []
  with Pool(args.procs) as p:
    for i, r in enumerate(p.imap_unordered(one, jobs), 1):
      parts.append(r)
      if i % 50 == 0 or i == len(jobs):
        print(f"{i}/{len(jobs)} views", flush=True)
  out = pd.concat(parts).sort_values("union_row", ignore_index=True)
  path = OUT if args.views is None else OUT.with_suffix(".test.parquet")
  out.to_parquet(path, index=False)
  print(f"wrote {path} ({len(out)} rows)")


if __name__ == "__main__":
  main()
