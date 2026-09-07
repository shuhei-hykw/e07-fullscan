"""Check the integrate_smallregions port against the MATLAB reference.

``e07/matlab/work1.mat`` holds ``x`` (41,609 hits), ``lseg`` (the 1,239
segments MATLAB's stage 1 produced) and ``polylines`` (the 149 tracks
MATLAB's stage 2 produced from them). Feeding the reference ``lseg``
in isolates stage 2, so a mismatch here cannot be blamed on stage 1.

Polylines are compared as curves (Hausdorff distance after resampling)
rather than as vertex lists, and matched on geometry rather than on
array position. Two things make a stricter test meaningless: a track
has no head or tail, so traversal direction is arbitrary, and the
bend-finding search may place a vertex a few hits either side of the
same corner.

Exact agreement is capped at about half the polylines by design -- see
_ELL_SLACK_PX in module/graphdet/integrate.py for why the reference
run is not bit-reproducible.

  python scripts/check_polylines_reference.py [--mat PATH]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import scipy.io as sio
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.graphdet import integrate_smallregions

_DEFAULT_MAT = Path(__file__).parents[2] / "matlab" / "work1.mat"
# Agreement bands to report, in pixels.
_TOLERANCES = (1e-6, 0.5, 2.0, 5.0, 20.0)
# Step (px) at which polylines are resampled before comparison.
_SAMPLE_STEP_PX = 1.0
# Nearest reference centroids to score before giving up on a match.
_N_CANDIDATES = 12


def as_curve(p: np.ndarray, step: float = _SAMPLE_STEP_PX) -> np.ndarray:
  """Resample a polyline to evenly spaced points.

  The port and MATLAB may split the same track at different vertices,
  so comparing vertex lists would call an identical track a mismatch.
  Comparing the curves they trace does not.
  """
  s = np.concatenate(
    [[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
  if s[-1] == 0:
    return p[:1]
  t = np.arange(0.0, s[-1], step)
  return np.stack([np.interp(t, s, p[:, k]) for k in range(p.shape[1])],
                  axis=1)


def match(got: list, ref: list) -> np.ndarray:
  """Hausdorff distance from each polyline to its closest reference."""
  curves = [as_curve(p) for p in ref]
  trees = [cKDTree(c) for c in curves]
  centroids = np.array([p.mean(axis=0) for p in ref])
  out = np.full(len(got), np.inf)
  for i, p in enumerate(got):
    a = as_curve(p)
    near = np.argsort(
      np.linalg.norm(centroids - p.mean(axis=0), axis=1))[:_N_CANDIDATES]
    for j in near:
      out[i] = min(out[i], max(trees[j].query(a)[0].max(),
                               cKDTree(a).query(curves[j])[0].max()))
  return out


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--mat", type=Path, default=_DEFAULT_MAT)
  args = ap.parse_args()

  data = sio.loadmat(args.mat)
  x, lseg = data["x"], data["lseg"]
  ref = [np.asarray(p, dtype=float) for p in data["polylines"].ravel()]
  print(f"reference: {x.shape[0]} hits, {lseg.shape[2]} segments "
        f"-> {len(ref)} polylines")

  t0 = time.time()
  got = integrate_smallregions(x, lseg)
  elapsed = time.time() - t0
  print(f"port:      {len(got)} polylines in {elapsed:.1f} s")
  print(f"count difference: {len(got) - len(ref):+d}")

  def total_len(polys):
    return sum(float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
               for p in polys)

  print(f"vertices: reference {sum(p.shape[0] for p in ref)}, "
        f"port {sum(p.shape[0] for p in got)}")
  print(f"total track length: reference {total_len(ref):.0f} px, "
        f"port {total_len(got):.0f} px")

  d = match(got, ref)
  print("\nHausdorff distance to the closest reference polyline:")
  for tol in _TOLERANCES:
    n = int((d <= tol).sum())
    print(f"  <= {tol:<8g} px : {n:5d} / {d.size}  ({100 * n / d.size:5.1f}%)")
  print(f"  median {np.median(d):.4g} px, worst {d.max():.4g} px")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
