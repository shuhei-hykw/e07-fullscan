"""Stratified random audit of the merged vertex catalogue.

The catalogue holds ~1.5M candidates and nobody knows what fraction are
reactions. The specials only show that known vertices survive; they say
nothing about the rest of the list. This draws a random sample from
four exclusive strata of an operating budget, renders each candidate
for a blind human verdict, and keeps the inclusion probabilities so the
verdicts can be weighted back to the catalogue.

Strata, within each view: the top TOP_N candidates by n_tracks_max and
the top TOP_N by angle_spread_best x n_slices, giving
  both | ntrk_only | spnsl_only | neither
Ties are broken at random (fixed seed) so both rankings spend exactly
TOP_N per view. The two rankings are the ones used so far (May: sp x
nsl gave a much cleaner top list; September: n_tracks_max ranked the
known vertices best), so the audit compares them on the same
catalogue and budget.

  python scripts/vertex_audit.py sample [--per-stratum 100]
  python scripts/vertex_audit.py render [--pilot 10]
  python run.py review --crops results/vertex_audit_v7/crops \\
    --labels results/vertex_audit_v7/labels.csv \\
    --categories vertex,crossing,track,junk,unclear

render --pilot N renders only the first N of each stratum in the
blind order, a random subset of the full sample, so a pilot's verdicts
carry over when the rest is rendered. Each candidate gets <id>.png
(a 1024 px overview of the middle slice and a minimum-intensity
projection over the z range) and <id>/sNN.png, every slice of the
range at full resolution, which the review page steps through.

key.csv holds the stratum and ranks and must not be shown to the
reviewer; blind.csv and the crops carry only an id. sample refuses to
overwrite key.csv and render refuses crops made from a different
key, so images, key and verdicts cannot silently drift apart.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.reader import load_spng

_REPO = Path(__file__).resolve().parents[1]
_CATALOGUE = _REPO / "results" / "vertex_v7" / "vertices_merged.parquet"
_OUT = _REPO / "results" / "vertex_audit_v7"
_IMAGE_ROOT = Path(os.environ.get("E07_FULLSCAN_IMAGE",
                                  str(_REPO / "fullscan-image")))
# view_id in the catalogue is the kekcc path; everything after this
# prefix is the path under the image root.
_KEKCC_ROOT = "/gpfs/group/had/sks/E07/tohoku/fullscan/"
TOP_N = 20
PER_STRATUM = 100
SEED = 20261023
STRATA = ("both", "ntrk_only", "spnsl_only", "neither")
# Rendering. Slices: DETAIL_PX square at full resolution (0.29 um/px)
# for every slice of the candidate's z range plus Z_MARGIN each side.
# Overview: OVERVIEW_PX square of the middle slice shrunk to DETAIL_PX,
# beside the minimum-intensity projection (tracks are dark) of the
# detail square over the range.
DETAIL_PX = 512
OVERVIEW_PX = 1024
Z_MARGIN = 4
LABEL_SCALE = 0.6
LABEL_POS = (6, 20)
TICK_PX = 14
TICK_GAP = 16
WHITE = 255
YELLOW = (0, WHITE, WHITE)
RED = (0, 0, WHITE)
KEY_STAMP = "KEY_SHA256"


def local_view(view_id: str) -> Path:
  return _IMAGE_ROOT / view_id.removeprefix(_KEKCC_ROOT)


def strata_of(df: pd.DataFrame, rng) -> pd.DataFrame:
  df = df.assign(sp_nsl=df.angle_spread_best * df.n_slices,
                 tie=rng.random(len(df)))
  for col, rank in (("n_tracks_max", "rank_ntrk"), ("sp_nsl", "rank_spnsl")):
    order = df.sort_values(["view_id", col, "tie"],
                           ascending=[True, False, False])
    df.loc[order.index, rank] = order.groupby("view_id").cumcount() + 1
  a, b = df.rank_ntrk <= TOP_N, df.rank_spnsl <= TOP_N
  df["stratum"] = np.select([a & b, a & ~b, ~a & b],
                            STRATA[:3], default=STRATA[3])
  return df.drop(columns="tie")


def cmd_sample(args) -> None:
  key_path = args.out / "key.csv"
  if key_path.exists():
    raise SystemExit(f"{key_path} exists; a new sample would orphan its "
                     "crops and labels. Use another --out.")
  rng = np.random.default_rng(args.seed)
  df = strata_of(pd.read_parquet(args.catalogue), rng)
  picks = []
  for s in STRATA:
    pool = df[df.stratum == s]
    n = min(args.per_stratum, len(pool))
    take = pool.iloc[rng.choice(len(pool), n, replace=False)].copy()
    take["N_stratum"] = len(pool)
    take["p_incl"] = n / len(pool)
    picks.append(take)
    print(f"{s:<11} {len(pool):>9} candidates, {n} drawn")
  key = pd.concat(picks)
  # Blind order: the reviewer must not see strata in sequence
  key = key.iloc[rng.permutation(len(key))].reset_index(drop=True)
  key.insert(0, "audit_id", [f"{i + 1:03d}" for i in range(len(key))])
  args.out.mkdir(parents=True, exist_ok=True)
  key.to_csv(key_path, index=False)
  key[["audit_id", "view_id", "vx_px", "vy_px", "z_min", "z_max"]].to_csv(
    args.out / "blind.csv", index=False)
  print(f"wrote {key_path} and blind.csv ({len(key)} rows)")


def _crop(img: np.ndarray, cx: float, cy: float, size: int) -> np.ndarray:
  """size x size window centred on (cx, cy); outside the image is NaN,
  so the candidate is always at the centre."""
  out = np.full((size, size), np.nan, np.float32)
  x0, y0 = round(cx) - size // 2, round(cy) - size // 2
  sx0, sy0 = max(x0, 0), max(y0, 0)
  sx1 = min(x0 + size, img.shape[1])
  sy1 = min(y0 + size, img.shape[0])
  if sx1 > sx0 and sy1 > sy0:
    out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = img[sy0:sy1, sx0:sx1]
  return out


def _to_bgr(img: np.ndarray) -> np.ndarray:
  """Contrast-stretch the valid pixels; outside the image is black."""
  valid = ~np.isnan(img)
  out = np.zeros(img.shape, np.uint8)
  if valid.any():
    lo, hi = np.percentile(img[valid], (1, 99))
    v = (img[valid] - lo) / max(hi - lo, 1.0) * WHITE
    out[valid] = np.clip(v, 0, WHITE).astype(np.uint8)
  return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def _mark(p: np.ndarray, text: str) -> np.ndarray:
  c = p.shape[0] // 2
  # Ticks around the centre, leaving the vertex itself uncovered
  for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
    p1 = (c + dx * TICK_GAP, c + dy * TICK_GAP)
    p2 = (c + dx * (TICK_GAP + TICK_PX), c + dy * (TICK_GAP + TICK_PX))
    cv2.line(p, p1, p2, RED, 1)
  cv2.putText(p, text, LABEL_POS, cv2.FONT_HERSHEY_SIMPLEX, LABEL_SCALE,
              YELLOW, 1, cv2.LINE_AA)
  return p


def z_range(z: np.ndarray, row) -> range:
  """Slice indices covering the candidate's z span plus the margin;
  z may run either way with the slice index."""
  a = int(np.argmin(np.abs(z - row.z_min)))
  b = int(np.argmin(np.abs(z - row.z_max)))
  lo, hi = min(a, b), max(a, b)
  return range(max(lo - Z_MARGIN, 0), min(hi + Z_MARGIN, len(z) - 1) + 1)


def render_one(reader, row, cache: dict, out_dir: Path) -> None:
  z = reader.z_positions()
  idx = z_range(z, row)

  def slice_(i):
    if i not in cache:
      cache[i] = reader.read(i)
    return cache[i]

  sub = out_dir / row.audit_id
  sub.mkdir(exist_ok=True)
  details = []
  for i in idx:
    d = _crop(slice_(i), row.vx_px, row.vy_px, DETAIL_PX)
    details.append(d)
    um = (z[i] - z[idx[0]]) * 1000
    cv2.imwrite(str(sub / f"s{i:02d}.png"),
                _mark(_to_bgr(d), f"slice {i}  {um:+.0f} um"))
  mid = idx[len(idx) // 2]
  ov = _crop(slice_(mid), row.vx_px, row.vy_px, OVERVIEW_PX)
  ov = cv2.resize(_to_bgr(ov), (DETAIL_PX, DETAIL_PX),
                  interpolation=cv2.INTER_AREA)
  # Box of the detail window inside the overview
  q = DETAIL_PX * DETAIL_PX // OVERVIEW_PX // 2
  c = DETAIL_PX // 2
  cv2.rectangle(ov, (c - q, c - q), (c + q, c + q), RED, 1)
  ov = _mark(ov, f"overview slice {mid}")
  mip = _mark(_to_bgr(np.fmin.reduce(details)),
              f"min slices {idx[0]}-{idx[-1]}")
  cv2.imwrite(str(out_dir / f"{row.audit_id}.png"), np.hstack([ov, mip]))


def cmd_render(args) -> None:
  key_path = args.out / "key.csv"
  key = pd.read_csv(key_path, dtype={"audit_id": str})
  crops = args.out / "crops"
  crops.mkdir(parents=True, exist_ok=True)
  sha = hashlib.sha256(key_path.read_bytes()).hexdigest()
  stamp = crops / KEY_STAMP
  if stamp.exists() and stamp.read_text().strip() != sha:
    raise SystemExit(f"{crops} was rendered from a different key.csv")
  stamp.write_text(sha + "\n")
  if args.pilot:
    key = key.groupby("stratum", sort=False).head(args.pilot)
  for view_id, grp in key.groupby("view_id"):
    path = local_view(view_id)
    if not path.exists():
      print(f"missing {path}")
      continue
    reader, cache = load_spng(path), {}
    for row in grp.itertuples():
      if not (crops / f"{row.audit_id}.png").exists():
        render_one(reader, row, cache, crops)
  print(f"{len(list(crops.glob('*.png')))} candidates rendered in {crops}")


def main() -> int:
  ap = argparse.ArgumentParser()
  sub = ap.add_subparsers(dest="cmd", required=True)
  s = sub.add_parser("sample")
  s.add_argument("--catalogue", type=Path, default=_CATALOGUE)
  s.add_argument("--per-stratum", type=int, default=PER_STRATUM)
  s.add_argument("--seed", type=int, default=SEED)
  r = sub.add_parser("render")
  r.add_argument("--pilot", type=int, default=0,
                 help="render only the first N of each stratum")
  for p in (s, r):
    p.add_argument("--out", type=Path, default=_OUT)
  args = ap.parse_args()
  {"sample": cmd_sample, "render": cmd_render}[args.cmd](args)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
