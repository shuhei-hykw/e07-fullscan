import numpy as np
import pytest

from module.tracking import Track, find_tracks, preprocess


class _MockEntry:
  x, y, z = 0.0, 0.0, 10.0


class _MockReader:
  affine_p2s = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

  def __init__(self, img):
    self._img = img
    self.entries = [_MockEntry()]

  def __len__(self):
    return 1

  def read(self, idx):
    return self._img.copy()


def _foggy_line_image():
  """256x256 image: fog background=180, 3px horizontal track line=30."""
  img = np.full((256, 256), 180, dtype=np.uint8)
  for row in range(126, 129):
    img[row, 10:246] = 30
  return img


def _uniform_image():
  return np.full((256, 256), 128, dtype=np.uint8)


# --- Track dataclass ---

def test_track_fields_stored():
  t = Track(
    x1=1.0, y1=2.0, x2=3.0, y2=4.0, z=5.0,
    px1=10, py1=20, px2=30, py2=40,
    length_px=28.3, angle_deg=0.0,
    view_id="test.json",
  )
  assert t.x1 == 1.0
  assert t.y1 == 2.0
  assert t.z == 5.0
  assert t.px1 == 10
  assert t.py2 == 40
  assert t.view_id == "test.json"


# --- preprocess ---

def test_preprocess_returns_binary():
  img = _foggy_line_image()
  result = preprocess(img)
  unique = set(np.unique(result))
  assert unique <= {0, 255}


def test_preprocess_shape_preserved():
  img = _foggy_line_image()
  result = preprocess(img)
  assert result.shape == img.shape


def test_preprocess_uniform_image_is_all_zero():
  # uniform image → zero variance after fog removal → all-zero after Otsu
  img = _uniform_image()
  result = preprocess(img)
  assert np.all(result == 0)


# --- find_tracks ---

def test_find_tracks_returns_list():
  reader = _MockReader(_foggy_line_image())
  result = find_tracks(reader, 0, zpj_half=0)
  assert isinstance(result, list)


def test_find_tracks_detects_line():
  reader = _MockReader(_foggy_line_image())
  tracks = find_tracks(reader, 0, zpj_half=0)
  assert len(tracks) >= 1


def test_find_tracks_grain_properties_measured():
  reader = _MockReader(_foggy_line_image())
  tracks = find_tracks(reader, 0, zpj_half=0)
  for t in tracks:
    assert isinstance(t.n_grains, int)
    assert t.n_grains >= 0
    assert isinstance(t.width_px, float)
    assert isinstance(t.mean_intens, float)
    assert t.mean_intens >= 0.0


def test_find_tracks_line_has_grains():
  # the horizontal track should have grains detected along it
  reader = _MockReader(_foggy_line_image())
  tracks = find_tracks(reader, 0, zpj_half=0)
  # at least one track should have n_grains > 0 and mean_intens > 0
  assert any(t.n_grains > 0 for t in tracks)
  assert any(t.mean_intens > 0.0 for t in tracks)


def test_find_tracks_uniform_returns_empty():
  reader = _MockReader(_uniform_image())
  tracks = find_tracks(reader, 0, zpj_half=0)
  assert tracks == []


def test_find_tracks_view_id_stored():
  reader = _MockReader(_foggy_line_image())
  tracks = find_tracks(reader, 0, view_id="my/scan.json", zpj_half=0)
  assert all(t.view_id == "my/scan.json" for t in tracks)


def test_find_tracks_z_from_entry():
  reader = _MockReader(_foggy_line_image())
  tracks = find_tracks(reader, 0, zpj_half=0)
  assert all(t.z == _MockEntry.z for t in tracks)


def test_find_tracks_identity_affine_stage_eq_pixel():
  # identity affine: stage coords must equal pixel coords
  reader = _MockReader(_foggy_line_image())
  tracks = find_tracks(reader, 0, zpj_half=0)
  for t in tracks:
    assert abs(t.x1 - t.px1) < 1e-6
    assert abs(t.y1 - t.py1) < 1e-6
    assert abs(t.x2 - t.px2) < 1e-6
    assert abs(t.y2 - t.py2) < 1e-6


def test_find_tracks_pixel_coords_in_bounds():
  img = _foggy_line_image()
  h, w = img.shape
  reader = _MockReader(img)
  tracks = find_tracks(reader, 0, zpj_half=0)
  for t in tracks:
    assert 0 <= t.px1 < w
    assert 0 <= t.py1 < h
    assert 0 <= t.px2 < w
    assert 0 <= t.py2 < h


def test_find_tracks_affine_translation():
  # affine with translation (tx=100, ty=200)
  reader = _MockReader(_foggy_line_image())
  reader.affine_p2s = [1.0, 0.0, 0.0, 1.0, 100.0, 200.0]
  tracks = find_tracks(reader, 0, zpj_half=0)
  for t in tracks:
    assert abs(t.x1 - (t.px1 + 100.0)) < 1e-6
    assert abs(t.y1 - (t.py1 + 200.0)) < 1e-6
