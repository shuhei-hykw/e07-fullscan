"""Graph-detector (B') branch points on full-scan views, for the A + B'
union (module/pipeline/union.py). Same settings as union_inputs.py:
classifier export, cell 6, z 3.8, MATLAB constants otherwise (P0).

usage: fullscan_bprime.py [--views DIR] [--out DIR] [--first N]
                          [--last N] [--workers N]

One CSV per view (<view stem>.csv, header only when the view has no
branch points), written atomically, so a view with a file is finished
and a rerun skips it.
"""
import argparse
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import union_inputs as ui  # noqa: E402
from module.graphdet import E07_Z_SCALE, MATLAB_CONFIG  # noqa: E402
from module.track_classifier import (build_training_set,  # noqa: E402
                                     train_classifier)

VIEWS = (REPO / "fullscan-image/E07/MOD108/PL12/tohoku-v1/AREA00"
         / "IMAGE00_AREA00")
OUT = REPO / "results/fullscan_bprime"


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("--views", type=Path, default=VIEWS)
  ap.add_argument("--out", type=Path, default=OUT)
  ap.add_argument("--first", type=int, default=0)
  ap.add_argument("--last", type=int, default=None)
  ap.add_argument("--workers", type=int, default=ui.WORKERS)
  args = ap.parse_args()

  views = sorted(args.views.glob("*.json"))[args.first:args.last]
  if not views:
    sys.exit(f"no views under {args.views}")
  args.out.mkdir(parents=True, exist_ok=True)
  ui.WORKERS = args.workers
  clf = train_classifier(*build_training_set(REPO / "results/manual_labels"))
  cfg = replace(MATLAB_CONFIG.for_spacing(float(ui.CELL_PX)),
                z_scale=E07_Z_SCALE)
  for v in views:
    f = args.out / f"{v.stem}.csv"
    if f.exists():
      continue
    t0 = time.time()
    b, n_hits = ui.bprime(v, clf, cfg)
    tmp = f.with_suffix(".tmp")
    b.to_csv(tmp, index=False)
    os.replace(tmp, f)
    print(f"{v.stem}: {len(b)} branch points, {n_hits} hits, "
          f"{time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
  main()
