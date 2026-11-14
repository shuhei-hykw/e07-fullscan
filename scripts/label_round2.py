"""Blind crop labelling, round 2: sample sites and render crops.

The protocol is fixed in e07-g4-hypernuclei
output/labels/protocol_round2.md (ac135d6, 7c6d26e). Three review
rankers over the full-scan union are compared on real plate sites:
darkness (D), the frozen logistic (L, scores_full.parquet) and the
logistic without mean_intens (N, scores_nomi.parquet).

Sites: per ranker, candidates of the non-excluded views in score order,
greedily merged within SITE_UM in plate xy (the crop shows the whole z
stack); the order of the kept sites is the global rank. "In X's top
TOP" = within SITE_UM of one of X's first TOP sites. Groups are drawn in
GROUPS order without replacement (a site within SITE_UM of one already
drawn is skipped); a discordant group is split evenly over the RANK_BINS
of the ranker that selected it; "random" is uniform over the pool
candidates. REPEATS of the drawn sites are shown again under new ids, at
least REPEAT_GAP crops after the first showing.

Each site is cropped from the overlapping (non-excluded) view that
places it farthest from the image edge. A crop is <id>.png (a
CONTEXT_UM minimum projection over all slices with the CROP_UM box, and
the CROP_UM minimum projection) and <id>/sNN.png, every slice of the
CROP_UM box, UPSCALE x. key.csv (do not show to the labeller) maps ids
to sites, groups, ranks and scores; crops carry a SHA-256 stamp of it.

  python scripts/label_round2.py sample
  python scripts/label_round2.py render
  python run.py review --crops results/label_round2/crops \\
    --labels results/label_round2/labels.csv \\
    --categories 0_nothing,1_ambiguous,2_star,3_xi_like \\
    --click-required 2_star,3_xi_like
"""
import argparse
import hashlib
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from fullscan_bprime import VIEWS  # noqa: E402
from module.reader import load_spng  # noqa: E402
from segment_repro import (CENTRE_PX, IMAGE_PX, PX_TO_UM,  # noqa: E402
                           UM_TO_PX)

DIR = REPO / "results/fullscan_union"
OUT = REPO / "results/label_round2"
EXCLUDED = (REPO.parent / "e07-g4-hypernuclei/output/labels"
            / "excluded_background_views.txt")
SITE_UM = 25.0
TOP = 5000
RANK_BINS = ((0, 100), (100, 1000), (1000, 5000))
# (name, ranker that selects, ranker whose top it must miss, n)
GROUPS = (("L-only", "L", "D", 60), ("D-only", "D", "L", 60),
          ("N-only", "N", "L", 35), ("M-only", "L", "N", 35),
          ("both", "L", None, 40), ("random", None, None, 40))
REPEATS = 30
REPEAT_GAP = 100
SEED = 20261114
CROP_UM = 50.0
CONTEXT_UM = 150.0
UPSCALE = 6
CONTEXT_SCALE = 2
STRETCH_PCT = (1, 99)
UM_PER_MM = 1000.0
UM_PER_PX = 0.507
BOX = (0, 255, 255)
KEY_STAMP = "KEY_SHA256"


def prefix(view):
  return "_".join(view.split("_")[:4])


def pool():
  u = pd.read_parquet(DIR / "union.parquet",
                      columns=["view", "vx_px", "vy_px", "z_mean",
                               "z_best", "source", "view_x_mm",
                               "view_y_mm"])
  for c in ("view_x_mm", "view_y_mm"):
    u[c] = u.groupby("view")[c].transform("first")
  f = pd.read_parquet(DIR / "features.parquet",
                      columns=["union_row", "darkness"])
  u.loc[f.union_row.to_numpy(), "D"] = f.darkness.to_numpy()
  for k, name in (("L", "full"), ("N", "nomi")):
    s = pd.read_parquet(DIR / f"scores_{name}.parquet",
                        columns=["union_row", "review_score"])
    u.loc[s.union_row.to_numpy(), k] = s.review_score.to_numpy()
  u["z"] = np.where(u.source == "A", u.z_best, u.z_mean)
  cen = u[["view_x_mm", "view_y_mm"]].to_numpy() * UM_PER_MM
  xy = cen + (u[["vx_px", "vy_px"]].to_numpy() - CENTRE_PX) @ PX_TO_UM.T
  u["px"], u["py"] = xy[:, 0], xy[:, 1]
  excl = set(EXCLUDED.read_text().split())
  u["excluded"] = u.view.map(prefix).isin(excl)
  return u


def sites(u, col, n):
  """First n sites of ranker col: greedy merge within SITE_UM."""
  order = u.index[np.argsort(-u[col].to_numpy(), kind="stable")]
  xy = u[["px", "py"]].to_numpy()
  pos = {i: k for k, i in enumerate(u.index)}
  grid, kept = {}, []
  for i in order:
    p = xy[pos[i]]
    cx, cy = (p // SITE_UM).astype(int)
    near = any(np.hypot(*(xy[pos[j]] - p)) < SITE_UM
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)
               for j in grid.get((cx + dx, cy + dy), ()))
    if near:
      continue
    grid.setdefault((cx, cy), []).append(i)
    kept.append(i)
    if len(kept) == n:
      break
  return kept


def near_any(xy, ref):
  from scipy.spatial import cKDTree
  if not len(ref):
    return np.zeros(len(xy), bool)
  d, _ = cKDTree(ref).query(xy)
  return d < SITE_UM


def display_view(row, views, at):
  """Overlapping non-excluded view placing the site farthest from the
  edge, and the site's pixel position in it."""
  g = views.loc[row.view]
  best = None
  for dx in (-1, 0, 1):
    for dy in (-1, 0, 1):
      w = at.get((g.gx + dx, g.gy + dy))
      if w is None or views.loc[w].excluded:
        continue
      c = views.loc[w, ["cx", "cy"]].to_numpy(float)
      px = (np.array([row.px, row.py]) - c) @ UM_TO_PX.T + CENTRE_PX
      edge = min(px.min(), IMAGE_PX - 1 - px.max())
      if best is None or edge > best[0]:
        best = (edge, w, px)
  return best


def cmd_sample(args):
  key_path = args.out / "key.csv"
  if key_path.exists():
    raise SystemExit(f"{key_path} exists; the sample is fixed")
  rng = np.random.default_rng(SEED)
  u = pool()
  p = u[~u.excluded].dropna(subset=["D", "L", "N"])
  top = {k: sites(p, k, TOP) for k in ("D", "L", "N")}
  rank = {k: {i: r for r, i in enumerate(v)} for k, v in top.items()}
  xy = p[["px", "py"]]
  drawn, rows = [], []
  for name, sel, miss, n in GROUPS:
    if sel is None:
      cand = [list(rng.permutation(p.index))]
      quota = [n]
    else:
      ids = np.array(top[sel])
      ok = np.ones(len(ids), bool)
      if miss is not None:
        ok = ~near_any(xy.loc[ids].to_numpy(),
                       xy.loc[top[miss]].to_numpy())
      else:
        ok = near_any(xy.loc[ids].to_numpy(), xy.loc[top["D"]].to_numpy())
      ids = ids[ok]
      if name == "both":
        cand, quota = [list(rng.permutation(ids))], [n]
      else:
        r = np.array([rank[sel][i] for i in ids])
        cand = [list(rng.permutation(ids[(r >= a) & (r < b)]))
                for a, b in RANK_BINS]
        quota = [n // len(RANK_BINS) + (k < n % len(RANK_BINS))
                 for k in range(len(RANK_BINS))]
    for b, c in enumerate(cand):
      q, got = quota[b], 0
      for i in c:
        if got == q:
          break
        if drawn and near_any(xy.loc[[i]].to_numpy(),
                              xy.loc[drawn].to_numpy())[0]:
          continue
        drawn.append(i)
        rows.append({"union_row": i, "group": name,
                     "bin": (f"{RANK_BINS[b][0]}-{RANK_BINS[b][1]}"
                             if len(cand) > 1 else "")})
        got += 1
      if got < q:
        # A short bin passes its remainder on to the later bins
        print(f"{name} bin {b}: only {got} of {q}")
        rest = len(cand) - b - 1
        for k in range(rest):
          quota[b + 1 + k] += ((q - got) // rest
                               + (k < (q - got) % rest))
  key = pd.DataFrame(rows)
  for k in ("D", "L", "N"):
    key[k] = p.loc[key.union_row, k].to_numpy()
    xs = xy.loc[top[k]].to_numpy()
    from scipy.spatial import cKDTree
    d, j = cKDTree(xs).query(xy.loc[key.union_row].to_numpy())
    key[f"rank_{k}"] = np.where(d < SITE_UM, j, -1)
  views = (u.groupby("view")[["view_x_mm", "view_y_mm", "excluded"]]
           .first())
  views["cx"] = views.view_x_mm * UM_PER_MM
  views["cy"] = views.view_y_mm * UM_PER_MM
  g = views.index.str.extract(r"VX(\d+)_VY(\d+)").astype(int)
  views["gx"], views["gy"] = g[0].to_numpy(), g[1].to_numpy()
  at = {(a, b): v for v, (a, b) in views[["gx", "gy"]].iterrows()}
  disp = []
  for i in key.union_row:
    row = u.loc[i]
    edge, w, px = display_view(row, views, at)
    disp.append({"view": row.view, "source": row.source,
                 "vx_px": row.vx_px, "vy_px": row.vy_px,
                 "z_mm": row.z, "plate_x_um": row.px,
                 "plate_y_um": row.py, "display_view": w,
                 "display_x_px": px[0], "display_y_px": px[1],
                 "display_edge_px": edge})
  key = pd.concat([key, pd.DataFrame(disp)], axis=1)
  key["repeat_of"] = ""
  # Shuffle; repeats go at least REPEAT_GAP after their first showing
  order = list(rng.permutation(len(key)))
  early = [k for k in order[:len(order) - REPEAT_GAP]]
  for src in rng.choice(early, REPEATS, replace=False):
    lo = order.index(src) + REPEAT_GAP
    rep = key.iloc[src].copy()
    rep["repeat_of"] = str(src)
    key = pd.concat([key, rep.to_frame().T], ignore_index=True)
    order.insert(int(rng.integers(lo, len(order) + 1)), len(key) - 1)
  key = key.iloc[order].reset_index().rename(columns={"index": "row"})
  # repeat_of points to the crop id of the first showing
  first = {str(r): f"{k + 1:03d}" for k, r in enumerate(key.row)
           if not key.repeat_of.iloc[k]}
  key["repeat_of"] = key.repeat_of.map(lambda s: first.get(s, ""))
  key.insert(0, "crop_id", [f"{k + 1:03d}" for k in range(len(key))])
  args.out.mkdir(parents=True, exist_ok=True)
  key.drop(columns="row").to_csv(key_path, index=False)
  print(key.groupby("group").size().to_string())
  print(f"{len(key)} crops -> {key_path}")


def _crop(img, cx, cy, size):
  h = size // 2
  out = np.full((size, size), np.nan, np.float32)
  x0, y0 = int(round(cx)) - h, int(round(cy)) - h
  xs, ys = max(x0, 0), max(y0, 0)
  xe, ye = min(x0 + size, img.shape[1]), min(y0 + size, img.shape[0])
  if xe > xs and ye > ys:
    out[ys - y0:ye - y0, xs - x0:xe - x0] = img[ys:ye, xs:xe]
  return out


def _grey(a, lo, hi, scale):
  g = np.clip((np.nan_to_num(a, nan=lo) - lo) / max(hi - lo, 1e-6), 0, 1)
  g = (g * 255).astype(np.uint8)
  return cv2.resize(g, None, fx=scale, fy=scale,
                    interpolation=cv2.INTER_NEAREST)


def render_one(stack, row, out):
  crop_px = int(round(CROP_UM / UM_PER_PX)) | 1
  ctx_px = int(round(CONTEXT_UM / UM_PER_PX)) | 1
  cx, cy = row.display_x_px, row.display_y_px
  det = np.stack([_crop(s, cx, cy, crop_px) for s in stack])
  lo, hi = np.nanpercentile(det, STRETCH_PCT)
  sub = out / row.crop_id
  sub.mkdir(exist_ok=True)
  for i, d in enumerate(det):
    cv2.imwrite(str(sub / f"s{i:02d}.png"), _grey(d, lo, hi, UPSCALE))
  ctx = np.fmin.reduce([_crop(s, cx, cy, ctx_px) for s in stack])
  c = cv2.cvtColor(_grey(ctx, *np.nanpercentile(ctx, STRETCH_PCT),
                         CONTEXT_SCALE), cv2.COLOR_GRAY2BGR)
  a = (ctx_px - crop_px) // 2 * CONTEXT_SCALE
  b = a + crop_px * CONTEXT_SCALE
  cv2.rectangle(c, (a, a), (b, b), BOX, 1)
  mip = _grey(np.fmin.reduce(det), lo, hi, UPSCALE)
  mip = cv2.resize(mip, (c.shape[1], c.shape[0]),
                   interpolation=cv2.INTER_NEAREST)
  cv2.imwrite(str(out / f"{row.crop_id}.png"),
              np.hstack([c, cv2.cvtColor(mip, cv2.COLOR_GRAY2BGR)]))


def cmd_render(args):
  key_path = args.out / "key.csv"
  key = pd.read_csv(key_path, dtype={"crop_id": str, "repeat_of": str})
  crops = args.out / "crops"
  crops.mkdir(parents=True, exist_ok=True)
  sha = hashlib.sha256(key_path.read_bytes()).hexdigest()
  stamp = crops / KEY_STAMP
  if stamp.exists() and stamp.read_text().strip() != sha:
    raise SystemExit(f"{crops} was rendered from a different key.csv")
  stamp.write_text(sha + "\n")
  for view, grp in key.groupby("display_view"):
    todo = [r for r in grp.itertuples()
            if not (crops / f"{r.crop_id}.png").exists()]
    if not todo:
      continue
    stack = load_spng(VIEWS / f"{view}.json").read_stack()
    for row in todo:
      render_one(stack, row, crops)
  print(f"{len(list(crops.glob('*.png')))} crops in {crops}")


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("cmd", choices=["sample", "render"])
  ap.add_argument("--out", type=Path, default=OUT)
  args = ap.parse_args()
  {"sample": cmd_sample, "render": cmd_render}[args.cmd](args)


if __name__ == "__main__":
  main()
