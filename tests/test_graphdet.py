"""Tests for the MATLAB graph-detector port (module.graphdet).

The reference tests replay ``e07/matlab/work1.mat``, which stores both
the input hit cloud and the segments MATLAB produced from it, so the
port can be checked without a MATLAB installation. Set E07_MATLAB_DIR
if the MATLAB tree lives somewhere other than the sibling directory.
"""
import os
from pathlib import Path

import numpy as np
import pytest

from module.graphdet import (
  detect_lseg_smallregion, detect_lseg_view, iter_regions,
  split_into_linear_components,
)

MATLAB_DIR = Path(os.environ.get(
  "E07_MATLAB_DIR",
  str(Path(__file__).resolve().parents[2] / "matlab"),
))

# Round-off only: the port should reproduce MATLAB bit for bit.
_MAX_ENDPOINT_ERR_PX = 1e-6
# Sub-regions checked by the fast reference test.
_QUICK_REGIONS = 16


def _line(n, start, step):
  return np.array([np.asarray(start, float) + i * np.asarray(step, float)
                   for i in range(n)])


def _load_reference():
  import scipy.io as sio
  path = MATLAB_DIR / "work1.mat"
  if not path.exists():
    pytest.skip(f"MATLAB reference not found: {path}")
  data = sio.loadmat(path)
  return data["x"], data["lseg"]


def _closest_endpoint_error(got, ref):
  """Worst endpoint gap to the best-matching reference segment."""
  from scipy.spatial import cKDTree
  tree = cKDTree(ref.mean(axis=0).T)
  worst = 0.0
  for i in range(got.shape[2]):
    seg = got[:, :, i]
    _, idx = tree.query(seg.mean(axis=0), k=min(8, ref.shape[2]))
    best = min(
      min(max(np.linalg.norm(seg[0] - ref[:, :, j][a]),
              np.linalg.norm(seg[1] - ref[:, :, j][1 - a]))
          for a in (0, 1))
      for j in np.atleast_1d(idx))
    worst = max(worst, best)
  return worst


def test_empty_region_returns_no_segments():
  assert detect_lseg_smallregion(np.zeros((0, 3))).shape == (2, 3, 0)


def test_single_hit_is_not_a_segment():
  # A lone hit cannot support a line, and subfunc2 drops any column
  # holding one point or fewer.
  assert detect_lseg_smallregion(np.array([[10.0, 10.0, 5.0]])).shape[2] == 0


def test_straight_track_recovered_end_to_end():
  x = _line(20, (10, 20, 5), (3, 1.5, 0))
  seg = detect_lseg_smallregion(x)
  assert seg.shape[2] == 1
  ends = sorted(seg[:, :, 0].tolist())
  assert np.allclose(ends[0], x[0])
  assert np.allclose(ends[1], x[-1])


def test_stray_hit_is_dropped():
  x = np.vstack([_line(20, (10, 20, 5), (3, 1.5, 0)), [[70.0, 90.0, 40.0]]])
  assert detect_lseg_smallregion(x).shape[2] == 1


def test_two_separated_tracks_split_into_components():
  x = np.vstack([_line(15, (5, 5, 3), (4, 0, 0)),
                 _line(15, (5, 90, 60), (0, 3, 0))])
  labels = split_into_linear_components(x)
  assert labels.max() == 2
  assert set(labels[:15]) != set(labels[15:])


def test_region_grid_covers_the_view_without_overlap():
  x = np.random.default_rng(0).uniform(
    [0.5, 0.5, 0.5], [2048, 2048, 80], size=(4000, 3))
  taken = sum(sub.shape[0] for _, _, sub in iter_regions(x))
  assert taken == x.shape[0]


def test_reference_first_regions_match_matlab():
  """Fast slice of the reference check: the first 16 sub-regions."""
  x, ref = _load_reference()
  sub = [(lb, hits) for k, lb, hits in iter_regions(x)
         if k < _QUICK_REGIONS]
  got = []
  for lb, hits in sub:
    seg = detect_lseg_smallregion(hits)
    if seg.shape[2]:
      got.append(seg + lb[None, :, None])
  got = np.concatenate(got, axis=2)
  assert _closest_endpoint_error(got, ref) < _MAX_ENDPOINT_ERR_PX


@pytest.mark.slow
def test_reference_full_view_matches_matlab():
  """All 256 sub-regions: same segment count, same geometry."""
  x, ref = _load_reference()
  got, counts = detect_lseg_view(x)
  assert counts.sum() == got.shape[2]
  assert got.shape[2] == ref.shape[2]
  assert _closest_endpoint_error(got, ref) < _MAX_ENDPOINT_ERR_PX
