"""Integration tests for known double-hypernuclei events in specials_x20.

These are confirmed reaction vertices from E07 emulsion analysis.
The pipeline MUST detect a multi-track vertex in each event.

Run with:  pytest -m slow tests/test_specials.py
Skip by default in regular pytest runs (too slow for CI).

Note: min_angle_spread=0 is used deliberately — some events (D013, T004,
T011) have angular spread < 20° at their primary vertex, so the production
filter would miss them.  These tests validate that the *pipeline* finds
the event, not that any particular filter setting is optimal.

Ground truth positions are in tests/specials_gt.json (XY pixel + Z in μm),
recorded by expert click session 2026-05-12. Tolerance: 200 px XY, 30 μm Z.
test_special_vertex_position currently fails for most events — this documents
the pipeline gap and defines the improvement target.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pandas as pd
import pytest

SPECIALS_DIR = Path(os.environ.get(
  "E07_SPECIALS_DIR",
  "/gpfs/group/had/sks/Users/shuhei/work/specials_x20",
))

# All confirmed event directories (image.json required)
_ALL_EVENTS = [
  "D005",
  "D013",
  "IBUKI",
  "IRRAWADY",
  "KISO",
  "MINO",
  "NAGARA",
  "T004",
  "T004_3body",
  "T004_center",
  "T011",
  "T011_100",
  "T011_200",
]

# Minimum n_tracks to call the event "detected"
_MIN_N_TRACKS = 5


_GT_PATH = Path(__file__).parent / "specials_gt.json"
_GT: dict = json.loads(_GT_PATH.read_text()) if _GT_PATH.exists() else {}
_GT_EVENTS: list[str] = list(_GT.get("events", {}).keys())


def _run_pipeline(
  json_path: Path,
) -> pd.DataFrame:
  """Run track finding + vertex finding on a specials event.

  Returns the raw (per-slice) vertex DataFrame.
  Uses conservative parameters to ensure all confirmed events pass:
  - min_angle_spread=0  (some events have spread < 20° at true vertex)
  - beam_angle_cut=0    (beam direction may differ from fullscan)
  """
  import sys
  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
  from e07fullscan.io import load_spng
  from e07fullscan.tracking import find_tracks
  from e07fullscan.clustering import find_vertices

  reader = load_spng(json_path)
  px_scale = reader.affine_p2s[0] * 1000.0  # mm/px -> um/px
  stack = reader.read_stack()

  rows: list[dict] = []
  for idx in range(len(reader)):
    for t in find_tracks(
      reader, idx=idx, view_id=str(json_path),
      px_scale_um=px_scale, _stack=stack,
    ):
      d = t.__dict__.copy()
      d["slice_idx"] = idx
      rows.append(d)

  if not rows:
    return pd.DataFrame()

  df = pd.DataFrame(rows)
  return find_vertices(
    df,
    min_tracks=3,
    max_ep=150.0,
    max_ep_frac=0.5,
    min_intens=10.0,
    min_len_px=50.0,
    beam_angle_cut=0.0,
    min_angle_spread=0.0,
  )


def _run_pipeline_merged(json_path: Path) -> pd.DataFrame:
  """Run full pipeline including cross-slice merge. Returns merged vertices."""
  import sys
  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
  from e07fullscan.clustering import merge_vertex_slices

  vdf = _run_pipeline(json_path)
  if vdf.empty:
    return pd.DataFrame()
  return merge_vertex_slices(vdf, eps_xy=50.0, min_slices=1)


@pytest.mark.slow
@pytest.mark.parametrize("event", _ALL_EVENTS)
def test_special_vertex_detected(event: str) -> None:
  """Confirmed reaction vertex must be found with n_tracks >= 5."""
  json_path = SPECIALS_DIR / event / "image.json"
  if not json_path.exists():
    pytest.skip(f"specials not found: {json_path}")

  vdf = _run_pipeline(json_path)

  assert not vdf.empty, (
    f"{event}: vertex finding returned no candidates"
  )
  n_max = int(vdf["n_tracks"].max())
  assert n_max >= _MIN_N_TRACKS, (
    f"{event}: best vertex has only {n_max} tracks "
    f"(need >= {_MIN_N_TRACKS})"
  )


@pytest.mark.slow
@pytest.mark.parametrize("event", _GT_EVENTS)
def test_special_vertex_position(event: str) -> None:
  """Merged vertex must be found within ground-truth XY+Z tolerance.

  Ground truth from expert click session (specials_gt.json).
  Tolerance: 200 px XY, 30 μm Z.
  Currently fails for most events — documents the pipeline improvement target.
  """
  json_path = SPECIALS_DIR / event / "image.json"
  if not json_path.exists():
    pytest.skip(f"specials not found: {json_path}")

  gt = _GT["events"][event]
  tol_xy = _GT["tolerance_xy_px"]
  tol_z = _GT["tolerance_z_um"]
  tvx, tvy, tz = gt["vx"], gt["vy"], gt["z_um"]

  mdf = _run_pipeline_merged(json_path)
  assert not mdf.empty, f"{event}: no merged vertices"

  mdf["dist_xy"] = ((mdf.vx_px - tvx)**2 + (mdf.vy_px - tvy)**2)**0.5
  mdf["dist_z"] = (mdf.z_mean - tz).abs()
  close = mdf[(mdf.dist_xy < tol_xy) & (mdf.dist_z < tol_z)]

  if close.empty:
    best_xy = mdf.nsmallest(1, "dist_xy").iloc[0]
    pytest.fail(
      f"{event}: no merged vertex within {tol_xy}px XY + {tol_z}μm Z "
      f"of true ({tvx},{tvy},z={tz:.1f}μm). "
      f"Closest XY: dist={best_xy.dist_xy:.0f}px "
      f"n={int(best_xy.n_tracks_max)} "
      f"at ({int(best_xy.vx_px)},{int(best_xy.vy_px)}) "
      f"z_mean={best_xy.z_mean:.1f}μm"
    )

  best = close.nlargest(1, "n_tracks_max").iloc[0]
  assert int(best.n_tracks_max) >= _MIN_N_TRACKS, (
    f"{event}: vertex near true position has only "
    f"{int(best.n_tracks_max)} tracks (need >= {_MIN_N_TRACKS})"
  )


@pytest.mark.slow
@pytest.mark.parametrize("event", _ALL_EVENTS)
def test_special_reader_loads(event: str) -> None:
  """SpngReader must load every slice without error."""
  json_path = SPECIALS_DIR / event / "image.json"
  if not json_path.exists():
    pytest.skip(f"specials not found: {json_path}")

  from e07fullscan.io import load_spng
  reader = load_spng(json_path)
  assert len(reader) > 0
  # read first and last slice
  img0 = reader.read(0)
  imgN = reader.read(len(reader) - 1)
  assert img0.shape == imgN.shape
  assert img0.ndim == 2
