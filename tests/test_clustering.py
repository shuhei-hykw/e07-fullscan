import math

import pytest

from e07fullscan.tracking._track import Track
from e07fullscan.clustering import cluster_tracks


def _make_track(px1, py1, px2, py2, angle=None):
  if angle is None:
    angle = math.degrees(math.atan2(py2 - py1, px2 - px1)) % 180
  length = math.hypot(px2 - px1, py2 - py1)
  return Track(
    x1=float(px1), y1=float(py1),
    x2=float(px2), y2=float(py2),
    z=0.0,
    px1=px1, py1=py1, px2=px2, py2=py2,
    length_px=length,
    angle_deg=angle,
    view_id="test",
  )


def test_empty():
  assert cluster_tracks([]) == []


def test_single_track_unchanged():
  t = _make_track(0, 100, 100, 100)
  result = cluster_tracks([t])
  assert result == [t]


def test_identical_tracks_merged():
  t1 = _make_track(10, 100, 110, 100)
  t2 = _make_track(15, 100, 115, 100)  # same line, shifted slightly
  result = cluster_tracks([t1, t2], dist_eps=20.0, angle_eps=5.0)
  assert len(result) == 1


def test_different_angles_not_merged():
  t1 = _make_track(0, 100, 100, 100)   # horizontal
  t2 = _make_track(0, 100, 100, 200)   # ~45 deg
  result = cluster_tracks([t1, t2], dist_eps=20.0, angle_eps=5.0)
  assert len(result) == 2


def test_distant_parallel_lines_not_merged():
  t1 = _make_track(0, 0,   200, 0)    # y=0
  t2 = _make_track(0, 100, 200, 100)  # y=100, parallel but far
  result = cluster_tracks([t1, t2], dist_eps=20.0, angle_eps=5.0)
  assert len(result) == 2


def test_longest_track_is_representative():
  t_short = _make_track(50, 100, 80, 100)   # length 30
  t_long  = _make_track(10, 100, 110, 100)  # length 100, same line
  result = cluster_tracks([t_short, t_long], dist_eps=20.0, angle_eps=5.0)
  assert len(result) == 1
  assert result[0].length_px == pytest.approx(100.0)


def test_multiple_clusters():
  # cluster A: horizontal near y=100
  a1 = _make_track(0,   100, 100, 100)
  a2 = _make_track(5,   100, 105, 100)
  # cluster B: horizontal near y=300
  b1 = _make_track(0,   300, 100, 300)
  b2 = _make_track(3,   300, 103, 300)
  result = cluster_tracks([a1, a2, b1, b2], dist_eps=20.0, angle_eps=5.0)
  assert len(result) == 2


def test_collinear_fragments_merged():
  # Two collinear fragments of the same long line
  t1 = _make_track(0,  100, 50,  100)
  t2 = _make_track(60, 100, 120, 100)
  result = cluster_tracks([t1, t2], dist_eps=20.0, angle_eps=5.0)
  assert len(result) == 1
