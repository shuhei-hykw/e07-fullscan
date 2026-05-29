#!/usr/bin/env python3
"""Low-sp specials failure-mode diagnostic.

For each low-sp confirmed special (T011/T004/D013), walks the conventional
Hough branch at the clicked ground-truth vertex and records *where* the chain
breaks, into four categories:

  cat 1  tracks lost in preprocessing / noise removal
  cat 2  tracks survive but Hough line extraction misses them near GT
  cat 3  Hough lines exist + endpoints cluster near GT, but no vertex forms
  cat 4  vertex forms near GT, endpoints plausible, but angle spread is low
         (genuine forward-boosted / low-sp topology -> graph-branch candidate)

Design agreed with Codex (discussion 2026-05-28 19:04 / 19:11):
  - two radii: R=200 px (primary, = GT tolerance), R=300 px (sensitivity)
  - both single-slice and merged-window results, labelled separately
  - Hough metrics use line BODY proximity, not only endpoints
  - the near-GT Hough angular spread separates cat 4 (true low-sp) from
    a preprocessing / extraction miss

Batch functions are called directly (no server). GT from tests/specials_gt.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from e07fullscan.io import load_spng                              # noqa: E402
from e07fullscan.tracking._finder import preprocess              # noqa: E402
from e07fullscan.clustering import find_vertices, merge_vertex_slices  # noqa: E402
from e07fullscan.clustering._vertex import _angle_spread_deg     # noqa: E402
from e07fullscan.diagnostics import (                            # noqa: E402
    TRACK_CFG, tracks_to_df, projection, find_tracks_cfg,
)

R_PRIMARY = 200.0   # px, = GT tolerance
R_SENS = 300.0      # px, sensitivity window
WINDOW = 12         # +/- slices for the merged "would the catalog see it" pass

GT_PATH = ROOT / "tests" / "specials_gt.json"
OUT_DIR = ROOT / "results" / "lowsp_diag"
EVENTS = ["T011", "T004", "D013"]


def seg_dist(px, py, x1, y1, x2, y2) -> float:
    """Distance from point (px,py) to segment (x1,y1)-(x2,y2)."""
    vx, vy = x2 - x1, y2 - y1
    wx, wy = px - x1, py - y1
    L2 = vx * vx + vy * vy
    if L2 < 1e-9:
        return float(np.hypot(wx, wy))
    s = max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
    return float(np.hypot(px - (x1 + s * vx), py - (y1 + s * vy)))


def fg_fraction_near(binary, gx, gy, r) -> float:
    h, w = binary.shape
    ys, xs = np.ogrid[:h, :w]
    mask = (xs - gx) ** 2 + (ys - gy) ** 2 <= r * r
    tot = int(mask.sum())
    return float((binary[mask] > 0).mean()) if tot else 0.0


def hough_metrics(tracks, gx, gy, r) -> dict:
    """Endpoint support, line-body proximity, angular spread within r of GT."""
    ep_in = 0
    body_in = 0
    min_body = float("inf")
    body_angles = []
    for t in tracks:
        ep = min(np.hypot(t.px1 - gx, t.py1 - gy),
                 np.hypot(t.px2 - gx, t.py2 - gy))
        if ep <= r:
            ep_in += 1
        d = seg_dist(gx, gy, t.px1, t.py1, t.px2, t.py2)
        min_body = min(min_body, d)
        if d <= r:
            body_in += 1
            body_angles.append(t.angle_deg)
    spread = (_angle_spread_deg(np.array(body_angles))
              if len(body_angles) >= 2 else float("nan"))
    return {
        "ep_in": ep_in, "body_in": body_in,
        "min_body": (None if min_body == float("inf") else round(min_body, 1)),
        "angle_spread": spread, "n_angles": len(body_angles),
    }


def nearest_vertex(vdf, gx, gy, xcol="vx_px", ycol="vy_px") -> dict | None:
    if vdf is None or len(vdf) == 0:
        return None
    d = np.hypot(vdf[xcol].values - gx, vdf[ycol].values - gy)
    i = int(np.argmin(d))
    return {"row": vdf.iloc[i], "dist": float(d[i])}


def analyse(name: str, gt: dict) -> None:
    json_path = ROOT / "specials_x20" / name / "image.json"
    reader = load_spng(str(json_path))
    gx, gy, zc = gt["vx"], gt["vy"], gt["z_slice"]
    print(f"=== {name}  GT=({gx},{gy}) z_slice={zc}  "
          f"n_slices={len(reader)} ===")

    # ---- Stage 0: preprocess survival at GT slice ----
    proj, _, _ = projection(reader, zc)
    binary = preprocess(
        proj, fog_ksize=TRACK_CFG["fog_ksize"],
        noise_amin=TRACK_CFG["noise_amin"], noise_amax=TRACK_CFG["noise_amax"],
        noise_cmp=TRACK_CFG["noise_cmp"],
        noise_amax_upper=TRACK_CFG["noise_amax_upper"],
    )
    fg200 = fg_fraction_near(binary, gx, gy, R_PRIMARY)
    fg300 = fg_fraction_near(binary, gx, gy, R_SENS)
    print(f"  [0] fg fraction near GT: R200={fg200*100:.2f}%  "
          f"R300={fg300*100:.2f}%")

    # ---- Stage 1: Hough extraction at GT slice ----
    tracks_gt = find_tracks_cfg(reader, zc, str(json_path))
    for r in (R_PRIMARY, R_SENS):
        m = hough_metrics(tracks_gt, gx, gy, r)
        sp = (f"{m['angle_spread']:.1f}" if not np.isnan(m['angle_spread'])
              else "n/a")
        print(f"  [1] R{int(r)}: lines_total={len(tracks_gt)} "
              f"endpoints_in={m['ep_in']} body_in={m['body_in']} "
              f"min_body={m['min_body']} near_GT_spread={sp} "
              f"(n={m['n_angles']})")

    # ---- Stage 2a: single-slice vertex formation ----
    df_gt = tracks_to_df(tracks_gt, zc)
    vsingle = find_vertices(df_gt)
    ns = nearest_vertex(vsingle, gx, gy)
    if ns:
        r = ns["row"]
        print(f"  [2 single] nearest vertex dist={ns['dist']:.0f}px "
              f"n={int(r['n_tracks'])} sp={r['angle_spread']:.1f} "
              f"(within tol200={ns['dist'] <= R_PRIMARY})")
    else:
        print("  [2 single] no vertex formed on GT slice")

    # ---- Stage 2b: merged window (would the catalog see it?) ----
    lo = max(0, zc - WINDOW)
    hi = min(len(reader) - 1, zc + WINDOW)
    stack = reader.read_stack()
    frames = []
    for idx in range(lo, hi + 1):
        tk = find_tracks_cfg(reader, idx, str(json_path), stack=stack)
        frames.append(tracks_to_df(tk, idx))
    df_win = pd.concat(frames, ignore_index=True)
    vmerged = merge_vertex_slices(find_vertices(df_win))
    nm = nearest_vertex(vmerged, gx, gy)
    if nm:
        r = nm["row"]
        spb = r.get("angle_spread_best", float("nan"))
        print(f"  [2 merged +/-{WINDOW}] nearest vertex dist={nm['dist']:.0f}px "
              f"n_max={int(r['n_tracks_max'])} nsl={int(r['n_slices'])} "
              f"sp_best={spb:.1f} (within tol200={nm['dist'] <= R_PRIMARY})")
    else:
        print(f"  [2 merged +/-{WINDOW}] no merged vertex near GT")

    # ---- Stage 3: classification suggestion ----
    cat = classify(fg200, tracks_gt, gx, gy, ns, nm)
    print(f"  => suggested category: {cat}\n")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    half = int(R_SENS)
    crop = binary[max(0, gy - half):gy + half, max(0, gx - half):gx + half]
    cv2.imwrite(str(OUT_DIR / f"{name}_gt_binary.png"), crop)
    pc = proj[max(0, gy - half):gy + half, max(0, gx - half):gx + half]
    cv2.imwrite(str(OUT_DIR / f"{name}_gt_proj.png"), pc)


def classify(fg200, tracks_gt, gx, gy, ns, nm) -> str:
    m = hough_metrics(tracks_gt, gx, gy, R_PRIMARY)
    if fg200 < 0.005:
        return "cat 1 (no structure survives preprocessing near GT)"
    if m["body_in"] == 0:
        return "cat 2 (structure survives but no Hough lines near GT)"
    vertex_near = (ns and ns["dist"] <= R_PRIMARY) or \
                  (nm and nm["dist"] <= R_PRIMARY)
    if not vertex_near:
        return ("cat 3 (lines/endpoints near GT but no vertex within tol; "
                "merge/association limit)")
    sp = m["angle_spread"]
    if not np.isnan(sp) and sp < 28.0:
        return (f"cat 4 (vertex near GT but near-GT line spread {sp:.1f} deg "
                "< 28; genuine low-sp -> graph-branch candidate)")
    return ("vertex near GT with adequate spread; not obviously low-sp "
            "(re-examine GT or cut)")


def main() -> None:
    import json
    gt = json.loads(GT_PATH.read_text())["events"]
    print("Low-sp failure-mode diagnostic "
          "(batch functions called directly; server NOT used)\n")
    print(f"Hough: ml={TRACK_CFG['hough_min_line']} thr={TRACK_CFG['hough_thr']}"
          f"  find_vertices: defaults (min_tracks=3, min_angle_spread=0)\n")
    for name in EVENTS:
        analyse(name, gt[name])
    print(f"Saved near-GT proj/binary crops to {OUT_DIR}/")


if __name__ == "__main__":
    main()
