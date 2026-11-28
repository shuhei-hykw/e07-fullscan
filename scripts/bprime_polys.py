"""Save the B' polylines (graph-detector tracks) of every event of a
pseudo-image set, for the vertex-topology stage (topo_stage.py). The
B' run is the same as union_inputs.bprime (cell 6 px, classifier
denoise, production z scale); union_inputs keeps only the branch
points, this keeps the polylines.

One npz per event: xyz (concatenated polyline points; x, y in view px
with the export origin removed, z in stage mm), offsets (start of each
polyline in xyz, plus the total), mult/pts (branch points as in
union_inputs). Restartable (existing files are skipped); events run
in parallel with --procs.

  python scripts/bprime_polys.py DATASET [--real] [--procs N]
  # -> results/sim_eval/polys/<DATASET>{,_real}/evNNNN.npz
"""
import argparse
import json
import sys
from dataclasses import replace
from multiprocessing import Pool
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from module.graphdet import (E07_Z_SCALE, MATLAB_CONFIG,  # noqa: E402
                             attachment_codes, branch_points,
                             integrate_smallregions)
from module.graphdet.detectlseg import detect_lseg_view  # noqa: E402
from module.matlab_export import _ORIGIN_OFFSET, export_hits_grid  # noqa
from module.reader import load_spng  # noqa: E402
from module.track_classifier import (build_training_set,  # noqa: E402
                                     train_classifier)

IMAGES = REPO.parent / "e07-g4-hypernuclei/data/images"
OUT = REPO / "results/sim_eval/polys"
CELL_PX = 6
WORKERS = 2
PROCS = 12
CLF = None


def init():
  global CLF
  CLF = train_classifier(*build_training_set(REPO / "results/manual_labels"))


def one(job):
  path, out = job
  cfg = replace(MATLAB_CONFIG.for_spacing(float(CELL_PX)),
                z_scale=E07_Z_SCALE)
  pl = export_hits_grid(path, cell=CELL_PX, denoise_method="classifier",
                        classifier=CLF)
  x = pl[:, :3]
  seg, _ = detect_lseg_view(x, cfg=cfg, workers=WORKERS)
  polys = integrate_smallregions(x, seg, cfg)
  codes = attachment_codes(polys, x, cfg)
  pts, mult = branch_points(polys, x, codes, cfg)
  z = load_spng(path).z_positions()

  def to_view(p):
    p = np.asarray(p, float).reshape(-1, 3)
    return np.c_[p[:, :2] - _ORIGIN_OFFSET,
                 np.interp(p[:, 2] - _ORIGIN_OFFSET, np.arange(len(z)), z)]

  xyz = np.vstack([to_view(p) for p in polys]) if polys else np.zeros((0, 3))
  offsets = np.cumsum([0] + [len(p) for p in polys])
  np.savez_compressed(out, xyz=xyz, offsets=offsets, pts=to_view(pts),
                      mult=np.asarray(mult))
  return out.name


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("dataset")
  ap.add_argument("--real", action="store_true")
  ap.add_argument("--procs", type=int, default=PROCS)
  args = ap.parse_args()
  out = OUT / (args.dataset + ("_real" if args.real else ""))
  out.mkdir(parents=True, exist_ok=True)
  jobs = []
  for ev in sorted((IMAGES / args.dataset).glob("ev*")):
    path = (Path(json.loads((ev / "truth.json").read_text())
                 ["background_view"]) if args.real else ev / "image.json")
    if not (out / f"{ev.name}.npz").exists():
      jobs.append((path, out / f"{ev.name}.npz"))
  with Pool(args.procs, initializer=init) as p:
    for i, name in enumerate(p.imap_unordered(one, jobs), 1):
      print(f"{i}/{len(jobs)} {name}", flush=True)
  print(f"done {out}")


if __name__ == "__main__":
  main()
