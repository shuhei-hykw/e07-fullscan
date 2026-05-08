import math

import pandas as pd
import pytest

from e07fullscan.clustering import link_tracks


def _make_df(rows):
    """rows: list of (slice_idx, cx, cy, angle)"""
    data = []
    for slice_idx, cx, cy, angle in rows:
        half = 20
        dx = math.cos(math.radians(angle)) * half
        dy = math.sin(math.radians(angle)) * half
        data.append({
            "view_id":   "v.json",
            "slice_idx": slice_idx,
            "x1": cx - dx, "y1": cy - dy,
            "x2": cx + dx, "y2": cy + dy,
            "z": float(slice_idx) * -0.003,
            "px1": int(cx - dx), "py1": int(cy - dy),
            "px2": int(cx + dx), "py2": int(cy + dy),
            "length_px": 2 * half,
            "angle_deg": angle,
            "n_grains": 0, "width_px": 0.0, "mean_intens": 0.0,
        })
    return pd.DataFrame(data)


def test_single_slice_all_unique():
    df = _make_df([
        (0, 100, 100, 0),
        (0, 300, 300, 0),
    ])
    out = link_tracks(df)
    assert out["track_id"].nunique() == 2


def test_two_slices_linked():
    # same position and angle across two slices → should link
    df = _make_df([
        (0, 100, 100, 45),
        (1, 102, 100, 45),  # 2px shift → within max_dist=30
    ])
    out = link_tracks(df, max_dist=30, angle_eps=5)
    assert out["track_id"].nunique() == 1


def test_two_slices_too_far():
    df = _make_df([
        (0, 100, 100, 45),
        (1, 200, 200, 45),  # far away
    ])
    out = link_tracks(df, max_dist=30, angle_eps=5)
    assert out["track_id"].nunique() == 2


def test_angle_mismatch_not_linked():
    df = _make_df([
        (0, 100, 100, 0),
        (1, 101, 100, 90),  # close but different angle
    ])
    out = link_tracks(df, max_dist=30, angle_eps=5)
    assert out["track_id"].nunique() == 2


def test_multi_slice_chain():
    # track drifting slowly: should form one chain
    df = _make_df([
        (i, 100 + i * 2, 200, 30)
        for i in range(5)
    ])
    out = link_tracks(df, max_dist=30, angle_eps=5)
    assert out["track_id"].nunique() == 1
    assert len(out[out["track_id"] == out["track_id"].iloc[0]]) == 5


def test_two_parallel_tracks_not_merged():
    # two separate tracks, each spanning two slices
    df = _make_df([
        (0, 100, 100, 0),
        (1, 101, 100, 0),
        (0, 500, 500, 0),
        (1, 501, 500, 0),
    ])
    out = link_tracks(df, max_dist=30, angle_eps=5)
    assert out["track_id"].nunique() == 2


def test_track_id_column_exists():
    df = _make_df([(0, 100, 100, 0)])
    out = link_tracks(df)
    assert "track_id" in out.columns


def test_empty_df():
    df = pd.DataFrame(columns=[
        "view_id", "slice_idx", "x1", "y1", "x2", "y2", "z",
        "px1", "py1", "px2", "py2", "length_px", "angle_deg",
        "n_grains", "width_px", "mean_intens",
    ])
    out = link_tracks(df)
    assert len(out) == 0
