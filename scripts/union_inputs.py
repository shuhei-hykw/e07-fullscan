"""Method A + graphdet B' candidates on a pseudo-image set, for the A + B'
union study (discussion.md 2026-10-28 16:49 proposal).

usage: union_inputs.py DATASET [--real] [--first N] [--last N]

DATASET is a directory under e07-g4-hypernuclei/data/images. With --real
each event's truth.json background_view (the unmodified real view) is
processed instead, and outputs are named <DATASET>_real.

Writes to results/sim_eval/ (or --out):
  <name>_methodA_production.csv  production method-A candidates
  <name>_bprime.csv              B' branch points (P0 placement, z 3.8)
  <name>_events.csv              one row per finished event (counts,
                                 seconds), so an empty view is told
                                 apart from a missing one
  <name>.done                    written when every event is finished
Restartable: events already in _events.csv are skipped; rows of an
unfinished event are dropped on restart.
"""
import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import rank_specials as rs  # noqa: E402
from module.graphdet import (E07_Z_SCALE, MATLAB_CONFIG,  # noqa: E402
                             attachment_codes, branch_points,
                             integrate_smallregions)
from module.graphdet.detectlseg import detect_lseg_view  # noqa: E402
from module.matlab_export import _ORIGIN_OFFSET, export_hits_grid  # noqa
from module.pipeline import find_vertices, merge_vertex_slices  # noqa
from module.reader import load_spng  # noqa: E402
from module.track_classifier import (build_training_set,  # noqa: E402
                                     train_classifier)

IMAGES = REPO.parent / "e07-g4-hypernuclei/data/images"
OUT = REPO / "results/sim_eval"
CELL_PX = 6
WORKERS = 12


def method_a(path):
  tracks = rs.tracks_of(path)
  if tracks.empty:
    return pd.DataFrame(columns=["vx_px"])
  vdf = find_vertices(tracks, **rs._PRODUCTION)
  if vdf.empty:
    return pd.DataFrame(columns=["vx_px"])
  return merge_vertex_slices(vdf, eps_xy=rs._MERGE_EPS_XY,
                             min_slices=rs._MERGE_MIN_SLICES)


def bprime(path, clf, cfg):
  pl = export_hits_grid(path, cell=CELL_PX, denoise_method="classifier",
                        classifier=clf)
  x = pl[:, :3]
  seg, _ = detect_lseg_view(x, cfg=cfg, workers=WORKERS)
  polys = integrate_smallregions(x, seg, cfg)
  codes = attachment_codes(polys, x, cfg)
  pts, mult = branch_points(polys, x, codes, cfg)
  z = load_spng(path).z_positions()
  n = len(pts)
  zmm = (np.interp(pts[:, 2] - _ORIGIN_OFFSET, np.arange(len(z)), z)
         if n else np.zeros(0))
  return pd.DataFrame({
    "vx_px": pts[:, 0] - _ORIGIN_OFFSET if n else [],
    "vy_px": pts[:, 1] - _ORIGIN_OFFSET if n else [],
    "z_mean": zmm, "z_min": zmm, "z_max": zmm,
    "n_tracks_max": mult if n else []}), len(x)


def append(df, path):
  # An empty view adds no rows; _events.csv records it.
  if df.empty:
    return
  df.to_csv(path, mode="a", header=not path.exists(), index=False)


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("dataset")
  ap.add_argument("--real", action="store_true",
                  help="process truth.json background_view instead")
  ap.add_argument("--first", type=int, default=0)
  ap.add_argument("--last", type=int, default=None)
  ap.add_argument("--out", type=Path, default=OUT)
  args = ap.parse_args()

  evs = sorted((IMAGES / args.dataset).glob("ev*"))
  if not evs:
    sys.exit(f"no events under {IMAGES / args.dataset}")
  name = args.dataset + ("_real" if args.real else "")
  out = args.out
  out.mkdir(parents=True, exist_ok=True)
  f_a = out / f"{name}_methodA_production.csv"
  f_b = out / f"{name}_bprime.csv"
  f_ev = out / f"{name}_events.csv"
  done = set(pd.read_csv(f_ev).event) if f_ev.exists() else set()
  # Drop candidate rows of an event that crashed before its event row.
  for f in (f_a, f_b):
    if f.exists():
      d = pd.read_csv(f)
      d[d.event.isin(done)].to_csv(f, index=False)

  clf = train_classifier(*build_training_set(REPO / "results/manual_labels"))
  cfg = replace(MATLAB_CONFIG.for_spacing(float(CELL_PX)),
                z_scale=E07_Z_SCALE)
  for ev in evs[args.first:args.last]:
    if ev.name in done:
      continue
    t0 = time.time()
    path = (Path(json.loads((ev / "truth.json").read_text())
                 ["background_view"]) if args.real else ev / "image.json")
    a = method_a(path)
    t1 = time.time()
    b, n_hits = bprime(path, clf, cfg)
    t2 = time.time()
    # Candidates first, the event row last: a crash in between leaves
    # the event unlisted, and its rows are dropped on restart.
    append(a.assign(event=ev.name)[["event"] + list(a.columns)], f_a)
    append(b.assign(event=ev.name)[["event"] + list(b.columns)], f_b)
    append(pd.DataFrame([{"event": ev.name, "view": str(path),
                          "n_methodA": len(a), "n_bprime": len(b),
                          "n_hits": n_hits, "sec_methodA": round(t1 - t0),
                          "sec_bprime": round(t2 - t1)}]), f_ev)
    print(f"{name} {ev.name}: A {len(a)}, B' {len(b)} ({n_hits} hits), "
          f"{t1 - t0:.0f} + {t2 - t1:.0f} s", flush=True)
  if set(pd.read_csv(f_ev).event) >= {e.name for e in evs}:
    (out / f"{name}.done").touch()
    print("done", name)


if __name__ == "__main__":
  main()
