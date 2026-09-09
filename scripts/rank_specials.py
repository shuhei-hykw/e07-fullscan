"""Where does a KNOWN reaction vertex rank among the candidates?

Every previous specials measurement asked whether the pipeline finds
the confirmed vertex, and it does -- tests/test_specials.py passes 35
of 35. That is recall, and recall was never the problem. The full-scan
catalogue now holds 1,516,569 merged vertices, so the only number that
decides whether it is usable is where the true one sits in the list.

Ground truth is the expert click session of 2026-05-12
(tests/specials_gt.json, 200 px XY / 30 um Z tolerance), so this needs
no new human input.

Two cut settings are reported, because they answer different
questions. "production" is what built results/vertex_v7, so its rank is
the operational number. "relaxed" drops the beam-angle and
angle-spread cuts, which some confirmed events fail at their own
primary vertex; comparing the two separates "the cut threw it away"
from "the ranking buried it".

  python scripts/rank_specials.py [--events D005,T004] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.reader import load_spng
from module.pipeline import find_tracks, find_vertices, merge_vertex_slices

_SPECIALS = Path(os.environ.get(
  "E07_SPECIALS_DIR",
  str(Path(__file__).resolve().parents[2] / "specials_x20")))
_GT_PATH = Path(__file__).resolve().parents[1] / "tests" / "specials_gt.json"
# Plates confirmed as E07 by the user on 2026-07-27; KISO and NAGARA
# are E373 and are reported separately.
_E07 = {"D005", "D013", "IBUKI", "IRRAWADY", "MINO", "T004", "T011"}

# The cuts that produced results/vertex_v7.
_PRODUCTION = dict(min_tracks=3, max_ep=150.0, max_ep_frac=0.5,
                   min_intens=10.0, min_len_px=50.0,
                   beam_angle_cut=15.0, min_angle_spread=20.0)
# Same, minus the two cuts some confirmed events fail.
_RELAXED = dict(_PRODUCTION, beam_angle_cut=0.0, min_angle_spread=0.0)
_MERGE_EPS_XY = 50.0
_MERGE_MIN_SLICES = 1
# Column the catalogue is ranked by when a human triages it.
_RANK_BY = "n_tracks_max"


def tracks_of(json_path: Path) -> pd.DataFrame:
  reader = load_spng(json_path)
  px_scale = reader.affine_p2s[0] * 1000.0
  stack = reader.read_stack()
  rows = []
  for idx in range(len(reader)):
    for t in find_tracks(reader, idx=idx, view_id=str(json_path),
                         px_scale_um=px_scale, _stack=stack):
      d = t.__dict__.copy()
      d["slice_idx"] = idx
      rows.append(d)
  return pd.DataFrame(rows)


def rank_of_truth(merged: pd.DataFrame, gt: dict, tol_xy: float,
                  tol_z_um: float) -> dict:
  """Rank (1-based) of the best candidate matching the true vertex."""
  if merged.empty:
    return {"n_cand": 0, "rank": None, "n_tracks": None, "dist_px": None}
  df = merged.sort_values(_RANK_BY, ascending=False).reset_index(drop=True)
  dx = df["vx_px"] - gt["vx"]
  dy = df["vy_px"] - gt["vy"]
  dist = (dx ** 2 + dy ** 2) ** 0.5
  near = dist <= tol_xy
  if "z_mean" in df and gt.get("z_um") is not None:
    # For specials, z_mean is already in um -- the same comparison
    # test_special_vertex_position makes. (The full-scan catalogue
    # carries z_mean in mm; the two readers differ.)
    near &= (df["z_mean"] - gt["z_um"]).abs() <= tol_z_um
  hits = df.index[near]
  if len(hits) == 0:
    return {"n_cand": len(df), "rank": None, "n_tracks": None,
            "dist_px": float(dist.min())}
  i = int(hits[0])
  return {"n_cand": len(df), "rank": i + 1,
          "n_tracks": int(df.loc[i, _RANK_BY]),
          "dist_px": float(dist[i])}


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--specials", type=Path, default=_SPECIALS)
  ap.add_argument("--events", default=None,
                  help="comma-separated subset (default: all with truth)")
  ap.add_argument("--out", type=Path, default=None)
  args = ap.parse_args()

  gt_all = json.loads(_GT_PATH.read_text())
  tol_xy = float(gt_all.get("tolerance_xy_px", 200))
  tol_z = float(gt_all.get("tolerance_z_um", 30))
  events = (args.events.split(",") if args.events
            else list(gt_all["events"].keys()))

  print(f"tolerance {tol_xy:.0f} px XY, {tol_z:.0f} um Z; "
        f"ranked by {_RANK_BY} descending\n")
  head = (f"{'event':<12} {'plate':<5} {'cuts':<10} {'cand':>6} "
          f"{'rank':>6} {'n_trk':>6} {'dist':>7}  time")
  print(head)
  out_rows = []
  for event in events:
    path = args.specials / event / "image.json"
    if not path.exists():
      print(f"{event:<12} (missing: {path})")
      continue
    t0 = time.time()
    tracks = tracks_of(path)
    for label, cuts in (("production", _PRODUCTION), ("relaxed", _RELAXED)):
      if tracks.empty:
        merged = pd.DataFrame()
      else:
        vdf = find_vertices(tracks, **cuts)
        merged = (merge_vertex_slices(vdf, eps_xy=_MERGE_EPS_XY,
                                      min_slices=_MERGE_MIN_SLICES)
                  if not vdf.empty else pd.DataFrame())
      r = rank_of_truth(merged, gt_all["events"][event], tol_xy, tol_z)
      plate = "E07" if event in _E07 else "E373"
      dist = ("-" if r["dist_px"] is None else f"{r['dist_px']:.0f}")
      print(f"{event:<12} {plate:<5} {label:<10} {r['n_cand']:6d} "
            f"{str(r['rank'] or '-'):>6} {str(r['n_tracks'] or '-'):>6} "
            f"{dist:>7}  {time.time() - t0:5.0f}s", flush=True)
      out_rows.append({"event": event, "plate": plate, "cuts": label, **r})
  if args.out:
    args.out.write_text(json.dumps(out_rows, indent=2))
    print(f"\nwrote {args.out}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
