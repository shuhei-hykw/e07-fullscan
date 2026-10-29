"""Union vertex candidates (method A + darkest B') of a pseudo-image set,
from the union_inputs.py outputs (module/pipeline/union.py).

usage: union_candidates.py DATASET [--real] [--k 770]

Reads results/sim_eval/<name>_{methodA_production,bprime,events}.csv
(<name> = DATASET or DATASET_real) and writes <name>_union.csv: the A
rows (source A), then the top-k B' rows of each event (source Bprime,
with darkness and dark_rank). Refuses a run set without its .done
marker.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from module.pipeline.union import TOP_K, union_candidates  # noqa: E402
from module.reader import load_spng  # noqa: E402

IMAGES = REPO.parent / "e07-g4-hypernuclei/data/images"
RESULTS = REPO / "results/sim_eval"


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("dataset")
  ap.add_argument("--real", action="store_true")
  ap.add_argument("--k", type=int, default=TOP_K)
  ap.add_argument("--results", type=Path, default=RESULTS)
  args = ap.parse_args()

  name = args.dataset + ("_real" if args.real else "")
  r = args.results
  if not (r / f"{name}.done").exists():
    sys.exit(f"{name}: no .done marker in {r}")
  evs = pd.read_csv(r / f"{name}_events.csv")
  a_all = pd.read_csv(r / f"{name}_methodA_production.csv")
  b_all = pd.read_csv(r / f"{name}_bprime.csv")
  out = []
  for ev, view in zip(evs.event, evs.view):
    reader = load_spng(Path(view))
    u = union_candidates(a_all[a_all.event == ev], b_all[b_all.event == ev],
                         reader.read_stack(), reader.z_positions(), args.k)
    out.append(u.assign(event=ev))
    print(name, ev, (u.source == "A").sum(), (u.source == "Bprime").sum(),
          flush=True)
  pd.concat(out, ignore_index=True).to_csv(r / f"{name}_union.csv",
                                           index=False)


if __name__ == "__main__":
  main()
