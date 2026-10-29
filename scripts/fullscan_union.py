"""Union vertex candidates of every full-scan view: method A (the
per-slice vertex catalogue merged across slices, as rank_specials.py)
plus the darkest B' branch points (module/pipeline/union.py).

usage: fullscan_union.py [--vertex DIR] [--bprime DIR] [--views DIR]
                         [--out FILE] [--procs N] [--partial]

Needs a B' CSV for every view (fullscan_bprime.py) and stops otherwise,
unless --partial (only the finished views; for an early look).
A views are matched to image views by file name.
"""
import argparse
import sys
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import rank_specials as rs  # noqa: E402
from fullscan_bprime import VIEWS  # noqa: E402
from module.pipeline import merge_vertex_slices  # noqa: E402
from module.pipeline.union import union_candidates  # noqa: E402
from module.reader import load_spng  # noqa: E402

VERTEX = REPO / "results/vertex_v7"
BPRIME = REPO / "results/fullscan_bprime"
OUT = REPO / "results/fullscan_union/union.parquet"
PROCS = 8


def one(job):
  view, vfile, bfile = job
  a = pd.read_parquet(vfile)
  a = (merge_vertex_slices(a, eps_xy=rs._MERGE_EPS_XY,
                           min_slices=rs._MERGE_MIN_SLICES)
       if len(a) else pd.DataFrame(columns=["vx_px", "vy_px"]))
  reader = load_spng(view)
  u = union_candidates(a, pd.read_csv(bfile), reader.read_stack(),
                       reader.z_positions())
  return u.assign(view=view.stem)


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("--vertex", type=Path, default=VERTEX)
  ap.add_argument("--bprime", type=Path, default=BPRIME)
  ap.add_argument("--views", type=Path, default=VIEWS)
  ap.add_argument("--out", type=Path, default=OUT)
  ap.add_argument("--procs", type=int, default=PROCS)
  ap.add_argument("--partial", action="store_true",
                  help="use only the views whose B' is finished")
  args = ap.parse_args()

  views = {v.stem: v for v in sorted(args.views.glob("*.json"))}
  vfiles = {}
  for f in sorted(args.vertex.glob("vertex_*.parquet")):
    ids = pd.read_parquet(f, columns=["view_id"]).view_id.unique()
    for i in ids:
      vfiles[Path(i).stem] = f
  missing = [s for s in views if not (args.bprime / f"{s}.csv").exists()
             or s not in vfiles]
  if missing and not args.partial:
    sys.exit(f"{len(missing)} views lack B' or A output, e.g. {missing[0]}")
  for m in missing:
    views.pop(m)
  jobs = [(views[s], vfiles[s], args.bprime / f"{s}.csv") for s in views]
  with Pool(args.procs) as p:
    out = p.map(one, jobs)
  args.out.parent.mkdir(parents=True, exist_ok=True)
  u = pd.concat(out, ignore_index=True)
  u.to_parquet(args.out, index=False)
  print(f"{len(views)} views, A {int((u.source == 'A').sum())}, "
        f"B' {int((u.source == 'Bprime').sum())} -> {args.out}")


if __name__ == "__main__":
  main()
