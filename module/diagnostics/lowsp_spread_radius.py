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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from module.io import load_spng                          # noqa: E402
from module.clustering import find_vertices             # noqa: E402
from module.clustering._vertex import _angle_spread_deg  # noqa: E402
from module.diagnostics import (                        # noqa: E402
  tracks_to_df, find_tracks_cfg,
)

RADII = [25, 50, 75, 100, 150, 200]
EVENTS = ["T011", "T004", "D013"]
GT_PATH = ROOT / "tests" / "specials_gt.json"


def main():
  gt = json.loads(GT_PATH.read_text())["events"]
  print("Spread vs endpoint-association radius "
        "(batch functions; server NOT used)\n")
  for name in EVENTS:
    g = gt[name]
    gx, gy, zc = g["vx"], g["vy"], g["z_slice"]
    reader = load_spng(str(ROOT / "specials_x20" / name / "image.json"))
    tracks = find_tracks_cfg(reader, zc, name)
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
