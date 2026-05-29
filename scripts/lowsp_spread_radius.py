#!/usr/bin/env python3
"""Test whether low vertex angle-spread is a clustering-fragmentation artifact.

Hypothesis (discussion 2026-05-28 19:37): for T011 the genuine multi-prong
star at the GT vertex is split by the 25 px intersection clustering (eps_px)
into a more-collinear sub-vertex, so the scalar vertex angle_spread (12.7 deg)
under-captures the real near-GT angular diversity (~32 deg).

Test: anchor at the detected vertex nearest GT on the GT slice, then sweep an
endpoint-association radius R and recompute angle_spread over all tracks whose
nearest endpoint lies within R of the anchor. If the low spread is a
fragmentation artifact, T011 should recover toward ~32 deg as R grows, while
a genuine low-sp core (T004) should stay low. D013 (already adequate) is a
positive control.

Batch functions called directly; no server.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e07fullscan.io import load_spng                          # noqa: E402
from e07fullscan.tracking import find_tracks                 # noqa: E402
from e07fullscan.clustering import find_vertices             # noqa: E402
from e07fullscan.clustering._vertex import _angle_spread_deg  # noqa: E402

TRACK_CFG = dict(
    zpj_half=4, fog_ksize=51,
    noise_amin=2, noise_amax=100, noise_cmp=50, noise_amax_upper=0,
    hough_thr=35, hough_min_line=30, hough_max_gap=5,
    grain_radius=15, px_scale_um=0.29,
)
RADII = [25, 50, 75, 100, 150, 200]
EVENTS = ["T011", "T004", "D013"]
GT_PATH = ROOT / "tests" / "specials_gt.json"

_DF_COLS = [
    "view_id", "slice_idx", "px1", "py1", "px2", "py2",
    "length_px", "angle_deg", "mean_intens", "z", "view_x_mm", "view_y_mm",
]


def tracks_to_df(tracks, slice_idx):
    return pd.DataFrame([{
        "view_id": t.view_id, "slice_idx": slice_idx,
        "px1": t.px1, "py1": t.py1, "px2": t.px2, "py2": t.py2,
        "length_px": t.length_px, "angle_deg": t.angle_deg,
        "mean_intens": t.mean_intens, "z": t.z,
        "view_x_mm": t.view_x_mm, "view_y_mm": t.view_y_mm,
    } for t in tracks], columns=_DF_COLS)


def main():
    gt = json.loads(GT_PATH.read_text())["events"]
    print("Spread vs endpoint-association radius "
          "(batch functions; server NOT used)\n")
    for name in EVENTS:
        g = gt[name]
        gx, gy, zc = g["vx"], g["vy"], g["z_slice"]
        reader = load_spng(str(ROOT / "specials_x20" / name / "image.json"))
        tcfg = {k: v for k, v in TRACK_CFG.items() if k != "px_scale_um"}
        tracks = find_tracks(
            reader, zc, view_id=name,
            px_scale_um=TRACK_CFG["px_scale_um"], **tcfg,
        )
        df = tracks_to_df(tracks, zc)
        vdf = find_vertices(df)
        if len(vdf):
            d = np.hypot(vdf["vx_px"] - gx, vdf["vy_px"] - gy)
            row = vdf.iloc[int(np.argmin(d))]
            ax, ay = float(row["vx_px"]), float(row["vy_px"])
            base_sp, base_n = float(row["angle_spread"]), int(row["n_tracks"])
        else:
            ax, ay, base_sp, base_n = gx, gy, float("nan"), 0

        # per-track nearest-endpoint distance to the anchor
        ep = np.minimum(
            np.hypot(df["px1"] - ax, df["py1"] - ay),
            np.hypot(df["px2"] - ax, df["py2"] - ay),
        ).values
        ang = df["angle_deg"].values

        print(f"=== {name}  GT=({gx},{gy}) z{zc}  anchor=({ax:.0f},{ay:.0f}) "
              f"detected-vertex sp={base_sp:.1f} n={base_n} ===")
        for R in RADII:
            sel = ep <= R
            n = int(sel.sum())
            sp = _angle_spread_deg(ang[sel]) if n >= 2 else float("nan")
            sp_s = f"{sp:5.1f}" if not np.isnan(sp) else "  n/a"
            print(f"  R={R:>3}px : n_tracks={n:>3}  angle_spread={sp_s} deg")
        print()


if __name__ == "__main__":
    main()
