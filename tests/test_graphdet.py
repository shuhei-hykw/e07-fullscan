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
  detect_lseg_smallregion, detect_lseg_view, inflection_nodes,
  integrate_smallregions, iter_regions, split_into_linear_components,
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


# Stage 2 cannot be reproduced bit for bit (see _ELL_SLACK_PX in
# module/graphdet/integrate.py); these are the bands the port holds to.
_MAX_POLY_HAUSDORFF_PX = 20.0
_SAMPLE_STEP_PX = 1.0


def _load_reference_polylines():
  import scipy.io as sio
  path = MATLAB_DIR / "work1.mat"
  if not path.exists():
    pytest.skip(f"MATLAB reference not found: {path}")
  data = sio.loadmat(path)
  return (data["x"], data["lseg"],
          [np.asarray(p, dtype=float) for p in data["polylines"].ravel()])


def _as_curve(p, step=_SAMPLE_STEP_PX):
  s = np.concatenate(
    [[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
  if s[-1] == 0:
    return p[:1]
  t = np.arange(0.0, s[-1], step)
  return np.stack([np.interp(t, s, p[:, k]) for k in range(p.shape[1])],
                  axis=1)


def _worst_hausdorff(got, ref):
  from scipy.spatial import cKDTree
  curves = [_as_curve(p) for p in ref]
  trees = [cKDTree(c) for c in curves]
  centroids = np.array([p.mean(axis=0) for p in ref])
  worst = 0.0
  for p in got:
    a = _as_curve(p)
    near = np.argsort(
      np.linalg.norm(centroids - p.mean(axis=0), axis=1))[:12]
    worst = max(worst, min(
      max(trees[j].query(a)[0].max(), cKDTree(a).query(curves[j])[0].max())
      for j in near))
  return worst


def test_no_segments_gives_no_polylines():
  assert integrate_smallregions(
    np.zeros((0, 3)), np.zeros((2, 3, 0))) == []


def test_collinear_segments_merge_into_one_track():
  # Two segments of one straight track, detected in adjacent regions
  # and separated by a small gap, must come back as a single polyline.
  hits = np.vstack([_line(40, (10, 10, 5), (3, 1, 0)),
                    _line(40, (140, 53, 5), (3, 1, 0))])
  lseg = np.stack([np.array([hits[0], hits[39]]),
                   np.array([hits[40], hits[79]])], axis=2)
  polys = integrate_smallregions(hits, lseg)
  assert len(polys) == 1
  assert np.linalg.norm(np.diff(polys[0], axis=0), axis=1).sum() > 240


def test_crossing_tracks_stay_separate():
  hits = np.vstack([_line(40, (10, 100, 5), (5, 0, 0)),
                    _line(40, (100, 10, 5), (0, 5, 0))])
  lseg = np.stack([np.array([hits[0], hits[39]]),
                   np.array([hits[40], hits[79]])], axis=2)
  assert len(integrate_smallregions(hits, lseg)) == 2


def test_inflection_nodes_finds_a_single_bend():
  x = np.vstack([_line(30, (0, 0, 0), (2, 0, 0)),
                 _line(30, (60, 2, 0), (0, 2, 0))])
  nodes = inflection_nodes(x, 3, 2.0)
  assert len(nodes) == 1
  assert 25 <= nodes[0] <= 35  # 1-based, near the 30th hit


@pytest.mark.slow
def test_reference_polylines_match_matlab():
  """Stage 2 replayed on the reference stage-1 segments."""
  x, lseg, ref = _load_reference_polylines()
  got = integrate_smallregions(x, lseg)
  assert len(got) == len(ref)
  assert _worst_hausdorff(got, ref) < _MAX_POLY_HAUSDORFF_PX
