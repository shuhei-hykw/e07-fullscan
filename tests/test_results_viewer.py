import io
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from module.server.app import create_app
from module.server.results import (
  ResultsStore, render_image, render_stats,
)

VIEW_ID = "scan.json"
H, W = 256, 256


@pytest.fixture
def sample_df():
  return pd.DataFrame({
    "view_id":   [VIEW_ID] * 3,
    "slice_idx": [0, 0, 1],
    "x1": [10.0, 50.0, 20.0], "y1": [20.0, 60.0, 30.0],
    "x2": [100.0, 150.0, 120.0], "y2": [25.0, 65.0, 35.0],
    "z":  [1.0, 1.0, 2.0],
    "px1": [10, 50, 20], "py1": [20, 60, 30],
    "px2": [100, 150, 120], "py2": [25, 65, 35],
    "length_px": [90.1, 100.0, 100.2],
    "angle_deg": [3.2, 2.9, 1.8],
  })


@pytest.fixture
def store(tmp_path, sample_df):
  p = tmp_path / "tracks.parquet"
  sample_df.to_parquet(p, index=False)
  return ResultsStore(p)


@pytest.fixture
def mock_reader():
  r = MagicMock()
  r.image_type.height = H
  r.image_type.width  = W
  return r


@pytest.fixture
def client(tmp_path, store, mock_reader):
  with patch(
    "module.server.app.load_spng", return_value=mock_reader
  ):
    app = create_app(tmp_path, results=store)
    app.config["TESTING"] = True
    with app.test_client() as c:
      yield c


# --- ResultsStore ---

def test_store_view_ids(store):
  assert VIEW_ID in store.view_ids()


def test_store_get_slice_count(store):
  assert len(store.get_slice(VIEW_ID, 0)) == 2


def test_store_get_slice_empty(store):
  assert len(store.get_slice(VIEW_ID, 99)) == 0


def test_store_slice_indices(store):
  assert store.slice_indices(VIEW_ID) == [0, 1]


# --- render helpers ---

def test_render_image_shape(sample_df):
  df = sample_df[sample_df["slice_idx"] == 0]
  img = render_image(df, H, W)
  assert img.shape == (H, W, 3)
  assert img.dtype == np.uint8


def test_render_image_has_green_pixels(sample_df):
  df = sample_df[sample_df["slice_idx"] == 0]
  img = render_image(df, H, W)
  assert img[:, :, 1].max() == 255


def test_render_image_empty_is_black(sample_df):
  df = sample_df[sample_df["slice_idx"] == 99]
  img = render_image(df, H, W)
  assert img.sum() == 0


def test_render_stats_returns_figure(sample_df):
  import matplotlib.pyplot as plt
  df = sample_df[sample_df["slice_idx"] == 0]
  fig = render_stats(df)
  assert hasattr(fig, "savefig")
  plt.close(fig)


def test_render_stats_empty_no_crash(sample_df):
  import matplotlib.pyplot as plt
  df = sample_df[sample_df["slice_idx"] == 99]
  fig = render_stats(df)
  plt.close(fig)


# --- routes ---

def test_results_page_200(client):
  resp = client.get("/results/")
  assert resp.status_code == 200


def test_result_image_returns_png(client):
  resp = client.get("/result_image/0/0")
  assert resp.status_code == 200
  assert resp.content_type == "image/png"


def test_result_stats_returns_png(client):
  resp = client.get("/result_stats/0/0")
  assert resp.status_code == 200
  assert resp.content_type == "image/png"


def test_result_image_empty_slice(client):
  resp = client.get("/result_image/0/99")
  assert resp.status_code == 200
  assert resp.content_type == "image/png"


def test_results_routes_absent_without_results(tmp_path):
  app = create_app(tmp_path)
  app.config["TESTING"] = True
  with app.test_client() as c:
    assert c.get("/results/").status_code == 404
