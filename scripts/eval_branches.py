"""Efficiency and purity of the graph detector's branch finding.

The first measurement of what this pipeline is actually worth. Stages
1 and 2 could only be checked against MATLAB's own output -- agreement
there says the port is faithful, not that the detector works.
``simdata8.mat`` carries the truth: ``Summary`` lists every simulated
track's start and end, and an endpoint shared by two or more tracks is
a real branch point (14 of them in event 1, multiplicity 2 to 6). The
commented-out block at detect_tracks.m L61-64 is where this comes from.

Distances are isotropic: one slice is ~10 px at the simulation's 3 um
spacing, so a raw Euclidean distance would treat a 1-slice error as a
1-pixel one.

  python scripts/eval_branches.py [--events 1-10] [--mat PATH]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import scipy.io as sio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.graphdet import (
  attachment_codes, branch_points, detect_branches, detect_lseg_view,
  integrate_smallregions,
)
from module.graphdet.geom import MATLAB_Z_SCALE, scale_z

_DEFAULT_MAT = Path(__file__).parents[2] / "matlab" / "simdata8.mat"
# Match radii to report, in isotropic px.
_TOLERANCES = (10.0, 25.0, 50.0, 100.0)
# Columns of Summary holding the start and end coordinates.
_START_COLS = slice(1, 4)
_END_COLS = slice(4, 7)


def true_branch_points(summary: np.ndarray):
  """Endpoints shared by two or more simulated tracks."""
  pts = np.vstack([summary[:, _START_COLS], summary[:, _END_COLS]])
  uniq, counts = np.unique(pts, axis=0, return_counts=True)
  keep = counts > 1
  return uniq[keep], counts[keep]


def parse_events(spec: str) -> list[int]:
  out: list[int] = []
  for part in spec.split(","):
    if "-" in part:
      lo, hi = part.split("-")
      out.extend(range(int(lo), int(hi) + 1))
    else:
      out.append(int(part))
  return out


def evaluate(data, event: int, verbose: bool) -> dict:
  summary = np.asarray(data["Summary"].ravel()[event - 1], dtype=float)
  hits = np.asarray(data["dspl"].ravel()[event - 1], dtype=float)[:, :3]
  args_event = event
  truth, truth_mult = true_branch_points(summary)
  print(f"event {args_event}: {summary.shape[0]} true tracks, "
        f"{hits.shape[0]} hits, {truth.shape[0]} true branch points "
        f"(multiplicity {truth_mult.min()}-{truth_mult.max()})")

  t0 = time.time()
  lseg, _ = detect_lseg_view(hits)
  t1 = time.time()
  polylines = integrate_smallregions(hits, lseg)
  t2 = time.time()
  codes = attachment_codes(polylines, hits)
  _, ids = detect_branches(polylines, hits, codes)
  found, found_mult = branch_points(polylines, hits, codes)
  t3 = time.time()
  print(f"stage 1: {lseg.shape[2]} segments ({t1 - t0:.1f} s)  "
        f"stage 2: {len(polylines)} polylines ({t2 - t1:.1f} s)  "
        f"stage 3: {int(ids.max()) if ids.size else 0} groups, "
        f"{found.shape[0]} branch points ({t3 - t2:.1f} s)")
  sizes = np.bincount(ids)[1:] if ids.size else np.zeros(0)
  print(f"         groups with 2+ tracks: {int((sizes > 1).sum())}, "
        f"largest {int(sizes.max()) if sizes.size else 0} tracks")

  if found.shape[0] == 0:
    print("no branch points found")
    return {"truth": truth.shape[0], "found": 0,
            "matched_truth": {t: 0 for t in _TOLERANCES},
            "matched_found": {t: 0 for t in _TOLERANCES}, "merged": 0}

  d = np.linalg.norm(
    scale_z(truth[:, None, :] - found[None, :, :], MATLAB_Z_SCALE), axis=2)
  to_truth, to_found = d.min(axis=1), d.min(axis=0)
  nearest = d.argmin(axis=1)
  # Several true vertices a few pixels apart can collapse into one
  # reconstructed vertex; counting each of them as "found" would
  # overstate how well the detector resolves them.
  merged = int(truth.shape[0]
               - np.unique(nearest[to_truth <= _TOLERANCES[1]]).size
               - int((to_truth > _TOLERANCES[1]).sum()))

  print("\n  radius     efficiency            purity")
  for tol in _TOLERANCES:
    eff, pur = (to_truth <= tol).mean(), (to_found <= tol).mean()
    print(f"  {tol:5.0f} px   {eff:5.1%} "
          f"({int((to_truth <= tol).sum()):2d}/{truth.shape[0]})      "
          f"{pur:5.1%} ({int((to_found <= tol).sum()):2d}/"
          f"{found.shape[0]})")
  print(f"  of the matched, {merged} share a reconstructed vertex with "
        "another true one")

  if verbose:
    print("\nper true branch point (isotropic px to the nearest found):")
    for p, mult, dist, near in zip(truth, truth_mult, to_truth, nearest):
      print(f"  {np.array2string(p, precision=0):22s} mult {mult}  "
            f"-> {dist:8.1f} px, found mult {found_mult[near]}")
  return {
    "truth": truth.shape[0], "found": found.shape[0], "merged": merged,
    "matched_truth": {t: int((to_truth <= t).sum()) for t in _TOLERANCES},
    "matched_found": {t: int((to_found <= t).sum()) for t in _TOLERANCES},
  }


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--mat", type=Path, default=_DEFAULT_MAT)
  ap.add_argument("--events", default="1")
  args = ap.parse_args()

  data = sio.loadmat(args.mat)
  events = parse_events(args.events)
  results = [evaluate(data, e, verbose=len(events) == 1) for e in events]
  if len(events) == 1:
    return 0

  n_truth = sum(r["truth"] for r in results)
  n_found = sum(r["found"] for r in results)
  print(f"\n=== {len(events)} events: {n_truth} true branch points, "
        f"{n_found} reconstructed ===")
  print("  radius     efficiency            purity")
  for tol in _TOLERANCES:
    t = sum(r["matched_truth"][tol] for r in results)
    f = sum(r["matched_found"][tol] for r in results)
    print(f"  {tol:5.0f} px   {t / n_truth:5.1%} ({t:3d}/{n_truth})    "
          f"  {f / n_found:5.1%} ({f:3d}/{n_found})")
  print(f"  of the matched, {sum(r['merged'] for r in results)} share a "
        "reconstructed vertex with another true one")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
