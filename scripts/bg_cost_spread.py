#!/usr/bin/env python3
"""Background-cost check for a wider spread-association radius.

The T011 spread-recovery test (2026-05-29) showed a wider endpoint-association
radius (R=50 px) recovers fragmented signal stars. This measures the *cost*:
does R=50 also promote crossing-track backgrounds above the sp=28 quality cut?

Method (agreed with Codex, discussion 2026-05-29 11:06): sample broad-catalog
vertices with n_tracks_max 8-10 (the crossing-track-dominated band), and for
each recompute angle_spread the same way as lowsp_spread_radius — over tracks
whose nearest endpoint lies within R of the catalog vertex anchor — at R=25
(tight) and R=50. Report how many cross sp=28 only under R=50, plus
distributions, with T011/D013/T004 as anchors.

Batch functions called directly; no server.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module.io import load_spng                          # noqa: E402
from module.clustering._vertex import _angle_spread_deg  # noqa: E402
from module.diagnostics import find_tracks_cfg           # noqa: E402

R_TIGHT = 25.0
R_WIDE = 50.0
SP_CUT = 28.0
N_SAMPLE = 80
SEED = 7
MERGED = ROOT / "results" / "vertices_merged_v6.parquet"


def anchor_spread(tracks, ax, ay, r) -> tuple[float, int]:
    if not tracks:
        return float("nan"), 0
    px1 = np.array([t.px1 for t in tracks], float)
    py1 = np.array([t.py1 for t in tracks], float)
    px2 = np.array([t.px2 for t in tracks], float)
    py2 = np.array([t.py2 for t in tracks], float)
    ang = np.array([t.angle_deg for t in tracks], float)
    ep = np.minimum(np.hypot(px1 - ax, py1 - ay),
                    np.hypot(px2 - ax, py2 - ay))
    sel = ep <= r
    n = int(sel.sum())
    sp = _angle_spread_deg(ang[sel]) if n >= 2 else float("nan")
    return sp, n


def main() -> None:
    df = pd.read_parquet(MERGED)
    band = df[(df["n_tracks_max"] >= 8) & (df["n_tracks_max"] <= 10)]
    rng = np.random.default_rng(SEED)
    idx = rng.choice(len(band), size=min(N_SAMPLE, len(band)), replace=False)
    sample = band.iloc[np.sort(idx)].reset_index(drop=True)
    print(f"Background-cost check (batch functions; server NOT used)")
    print(f"n=8-10 band: {len(band)}; sampled {len(sample)} (seed={SEED})")
    print(f"R_tight={R_TIGHT} R_wide={R_WIDE} sp_cut={SP_CUT}\n")

    rows = []
    for i, r in sample.iterrows():
        try:
            reader = load_spng(str(r["view_id"]))
        except Exception as e:                       # noqa: BLE001
            print(f"  skip {str(r['view_id'])[-40:]}: {e}")
            continue
        zpos = reader.z_positions()
        sl = int(np.argmin(np.abs(zpos - r["z_mean"])))
        tracks = find_tracks_cfg(reader, sl, str(r["view_id"]))
        ax, ay = float(r["vx_px"]), float(r["vy_px"])
        sp25, n25 = anchor_spread(tracks, ax, ay, R_TIGHT)
        sp50, n50 = anchor_spread(tracks, ax, ay, R_WIDE)
        rows.append({
            "view": str(r["view_id"]).split("/")[-1][:24],
            "n": int(r["n_tracks_max"]), "sp25": sp25, "sp50": sp50,
            "n25": n25, "n50": n50,
        })
        if (i + 1) % 10 == 0:
            print(f"  ...{i + 1}/{len(sample)}")

    res = pd.DataFrame(rows).dropna(subset=["sp25", "sp50"])
    print(f"\nUsable samples: {len(res)}\n")

    def summ(col):
        v = res[col].values
        return f"median={np.median(v):.1f}  p90={np.percentile(v, 90):.1f}"
    print(f"  R25 spread: {summ('sp25')}")
    print(f"  R50 spread: {summ('sp50')}")
    print(f"  delta (R50-R25): median="
          f"{np.median(res['sp50'] - res['sp25']):.1f}  "
          f"p90={np.percentile(res['sp50'] - res['sp25'], 90):.1f}\n")

    below25 = res["sp25"] < SP_CUT
    promoted = below25 & (res["sp50"] >= SP_CUT)
    print(f"  vertices below sp=28 at R25: {int(below25.sum())}")
    print(f"  of those, promoted >=28 at R50: {int(promoted.sum())} "
          f"({100 * promoted.sum() / max(1, below25.sum()):.0f}% of below-cut, "
          f"{100 * promoted.sum() / len(res):.0f}% of all)\n")

    top = res.assign(delta=res["sp50"] - res["sp25"]) \
             .sort_values("delta", ascending=False).head(6)
    print("  top inflation examples:")
    for _, t in top.iterrows():
        print(f"    {t['view']:<26} n={t['n']} "
              f"sp25={t['sp25']:5.1f} -> sp50={t['sp50']:5.1f} "
              f"(+{t['sp50'] - t['sp25']:.1f})")

    print("\n  anchors (from lowsp_spread_radius 2026-05-29):")
    print("    T011 (frag star)    sp25=28.5 -> sp50=34.3")
    print("    T004 (genuine core) sp25= 3.1 -> sp50= 3.7")
    print("    D013 (control)      sp25=29.2 -> sp50=27.2")


if __name__ == "__main__":
    main()
