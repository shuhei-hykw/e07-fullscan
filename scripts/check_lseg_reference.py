"""Check the detectlseg port against the MATLAB reference run.

``e07/matlab/work1.mat`` holds a full input/output pair: ``x`` is the
41,609-hit downsampled cloud of simulation event 1 and ``lseg`` is the
1,239 segments MATLAB's detectlseg_smallregion produced from it over
the 16 x 16 grid of sub-regions. Re-running the port on the same ``x``
and matching segment for segment tells us whether the port is faithful
-- no MATLAB installation required.

Segments are matched on geometry, not on position in the array, so a
different ordering inside a region does not count as a mismatch. Each
segment's two endpoints may also come out swapped: the sign of an SVD
axis is arbitrary and MATLAB and LAPACK need not agree, so both
pairings are tried.

  python scripts/check_lseg_reference.py [--mat PATH] [--limit N]
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
from module.graphdet import detect_lseg_view

_DEFAULT_MAT = Path(__file__).parents[2] / "matlab" / "work1.mat"
# Endpoint agreement bands to report, in pixels.
_TOLERANCES = (1e-6, 0.01, 0.1, 1.0, 5.0)
# Nearest reference midpoints to consider before scoring endpoints.
_N_CANDIDATES = 8


def segment_distance(a: np.ndarray, b: np.ndarray) -> float:
  """Largest endpoint displacement, under the better of two pairings."""
  direct = max(np.linalg.norm(a[0] - b[0]), np.linalg.norm(a[1] - b[1]))
  swapped = max(np.linalg.norm(a[0] - b[1]), np.linalg.norm(a[1] - b[0]))
  return min(direct, swapped)


def match(got: np.ndarray, ref: np.ndarray) -> np.ndarray:
  """Distance from each detected segment to its closest reference one."""
  ref_mid = ref.mean(axis=0).T
  tree = cKDTree(ref_mid)
  k = min(_N_CANDIDATES, ref_mid.shape[0])
  out = np.full(got.shape[2], np.inf)
  for i in range(got.shape[2]):
    seg = got[:, :, i]
    _, idx = tree.query(seg.mean(axis=0), k=k)
    for j in np.atleast_1d(idx):
      out[i] = min(out[i], segment_distance(seg, ref[:, :, j]))
  return out


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--mat", type=Path, default=_DEFAULT_MAT)
  ap.add_argument("--limit", type=int, default=None,
                  help="stop after this many sub-regions")
  args = ap.parse_args()

  data = sio.loadmat(args.mat)
  x, ref = data["x"], data["lseg"]
  print(f"reference: {x.shape[0]} hits -> {ref.shape[2]} segments")

  t0 = time.time()
  seen = {"n": 0}

  def progress(k, n_hits, n_seg):
    seen["n"] = k + 1
    if (k + 1) % 32 == 0:
      print(f"  region {k + 1}/256  {time.time() - t0:6.1f} s", flush=True)
    if args.limit is not None and k + 1 >= args.limit:
      raise StopIteration

  try:
    got, counts = detect_lseg_view(x, progress=progress)
  except StopIteration:
    print("stopped early; rerun without --limit for the full check")
    return 1
  elapsed = time.time() - t0

  print(f"port:      {got.shape[2]} segments in {elapsed:.1f} s "
        f"({elapsed / 256:.2f} s/region)")
  print(f"count difference: {got.shape[2] - ref.shape[2]:+d}")

  d = match(got, ref)
  print("\nendpoint agreement with the closest reference segment:")
  for tol in _TOLERANCES:
    n = int((d <= tol).sum())
    print(f"  <= {tol:<8g} px : {n:5d} / {d.size}  ({100 * n / d.size:5.1f}%)")
  print(f"  median {np.median(d):.4g} px, worst {d.max():.4g} px")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
