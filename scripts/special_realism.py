"""Realism of the sim capture appearance: do the real known special
events (results/specials_0507, gt.json) look like sim captures or like
the eye-good stars in the review features?

For each event, the maximum of each feature over the candidates near
the vertex is placed as a percentile within that event's own candidate
pool (all A and all B' points, no union cut):
  special  9 real crops, candidates within TOL_UM in xy and TOL_Z_UM
           of the clicked vertex (stage z interval, as in
           e07-g4-hypernuclei module/specials_review.py)
  capture  v26 embedded sim events, candidates with d_cap <= TOL_UM
           (peer simlabels, developed space)
  star     70 eye-good full-scan stars, union candidates within TOL_UM
           / TOL_Z_UM; the pool is the star's view (union only, so its
           B' part is the 770 darkest)
Controls (the same statistic where no event is): N_SHIFTS positions
shifted by SHIFT_UM in xy for specials and stars, and the real-
background twin (same capture positions) for captures. A dense spot
always has a high max, so only the event - control gap is meaningful.
Prints the quartiles over events per feature and a Mann-Whitney test
of specials against captures.

  python scripts/special_realism.py
  # -> results/sim_eval/special_realism.txt
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import mannwhitneyu

REPO = Path(__file__).resolve().parents[1]
PEER = REPO.parent / "e07-g4-hypernuclei"
sys.path.insert(0, str(REPO / "scripts"))
import cross_view_presence as cv  # noqa: E402

SIM = REPO / "results/sim_eval"
SPECIALS = REPO / "results/specials_0507"
LABELS = PEER / "output/simlabels"
SET = "v26_embed_nagara_dz4"
TOL_UM = 15.0
TOL_Z_UM = 30.0
PIXEL_UM = 0.507
UM_PER_MM = 1000.0
COLS = ["n_tracks_max", "n_slices", "mean_intens", "angle_spread_best",
        "darkness", "z_span_um"]
QS = (25, 50, 75)
N_SHIFTS = 20
SHIFT_UM = (125.0, 225.0)   # as the peer's 250-450 px shifts
SEED = 20261127
OUT = SIM / "special_realism.txt"


def load_candidates(path):
  """Per-event candidate xy (px) and stage z interval (mm), in file
  order (as e07-g4-hypernuclei module/efficiency.load_candidates;
  copied because this repo's `module` package shadows the peer's)."""
  out = {}
  for _, r in pd.read_csv(path).iterrows():
    if pd.notna(r.get("z_min")) and pd.notna(r.get("z_max")):
      z = tuple(sorted((r.z_min, r.z_max)))
    else:
      z = (r.z_mean, r.z_mean)
    ev = r.get("event")
    ev = ev if isinstance(ev, str) else Path(r.view_id).parent.name
    out.setdefault(ev, []).append({"col": r.vx_px, "row": r.vy_px, "z": z})
  return out


def pct_of_max(pool, near):
  """Percentile of max(feature over near rows) within pool, per COLS."""
  out = {}
  for c in COLS:
    v = pool[c].to_numpy(dtype=float)
    m = np.nanmax(v[near]) if np.isfinite(v[near]).any() else np.nan
    out[c] = (v[np.isfinite(v)] < m).mean() if np.isfinite(m) else np.nan
  return out


RNG = np.random.default_rng(SEED)


def add(rows, ctrl, pool, xy_um, zok, pos):
  """Event row at pos and N_SHIFTS shifted control rows (same z)."""
  def near(p):
    return (np.hypot(*(xy_um - p).T) <= TOL_UM) & zok
  m = near(pos)
  if not m.any():
    return
  rows.append(pct_of_max(pool, m))
  r = RNG.uniform(*SHIFT_UM, N_SHIFTS)
  phi = RNG.uniform(0.0, 2.0 * np.pi, N_SHIFTS)
  for p in pos + np.c_[r * np.cos(phi), r * np.sin(phi)]:
    m = near(p)
    if m.any():
      ctrl.append(pct_of_max(pool, m))


def specials():
  a = load_candidates(SIM / "specials_0507_methodA_production.csv")
  b = load_candidates(SIM / "specials_0507_bprime.csv")
  f = pd.read_parquet(SIM / "specials_0507_features.parquet")
  rows, ctrl = [], []
  for d in sorted(SPECIALS.iterdir()):
    if not (d / "gt.json").exists():
      continue
    gt = json.loads((d / "gt.json").read_text())
    g = f[f.event == d.name]
    cands = {"A": a.get(d.name, []), "Bprime": b.get(d.name, [])}
    c = [cands[s][i] for s, i in zip(g.source, g.cand_id)]
    xy = np.array([(q["col"], q["row"]) for q in c])
    z = np.array([q["z"] for q in c])
    dz = np.maximum(z[:, 0] - gt["z_mm"], gt["z_mm"] - z[:, 1]).clip(0)
    zok = dz * UM_PER_MM <= TOL_Z_UM
    pos = np.array([gt["vx"], gt["vy"]]) * PIXEL_UM
    add(rows, ctrl, g, xy * PIXEL_UM, zok, pos)
  return pd.DataFrame(rows), pd.DataFrame(ctrl)


def captures(feat_set, label_file):
  f = pd.read_parquet(SIM / f"{feat_set}_features.parquet")
  lab = pd.read_parquet(LABELS / label_file,
                        columns=["event", "source", "cand_id", "d_cap"])
  f = f.merge(lab, on=["event", "source", "cand_id"], validate="1:1")
  rows = []
  for _, g in f.groupby("event"):
    near = (g.d_cap <= TOL_UM).to_numpy()
    if near.any():
      rows.append(pct_of_max(g, near))
  return pd.DataFrame(rows)


def stars():
  d = cv.load()
  f = pd.read_parquet(cv.FEATURES).set_index("union_row")
  st = pd.read_csv(cv.STARS)
  views = d.groupby("view")[["view_x_mm", "view_y_mm"]].first()
  rows, ctrl = [], []
  for _, s in st.iterrows():
    g = d[d.view == s.view]
    p = (views.loc[s.view].to_numpy() * UM_PER_MM
         + (np.array([s.x_px, s.y_px]) - cv.CENTRE_PX) @ cv.PX_TO_UM.T)
    zok = (np.abs(g.z - s.z_best_mm * UM_PER_MM) <= TOL_Z_UM).to_numpy()
    add(rows, ctrl, f.loc[g.index], g[["px", "py"]].to_numpy(), zok, p)
  return pd.DataFrame(rows), pd.DataFrame(ctrl)


def main():
  lines = [f"max feature within {TOL_UM:g} um (z {TOL_Z_UM:g} um) as a "
           "percentile of the event's own pool; quartiles over events"]
  sp, sc = specials()
  st, stc = stars()
  real = {"v26_embed_nagara_dz4": "v19_bgonly_nagara_dz4"}[SET]
  sets = (("special", sp), ("special shifted", sc),
          ("capture", captures(SET, f"{SET}_emb.parquet")),
          ("capture real twin", captures(real, f"{SET}_real.parquet")),
          ("star", st), ("star shifted", stc))
  for name, t in sets:
    lines.append(f"{name} (n={len(t)})")
    for c in COLS:
      q = np.nanpercentile(t[c], QS)
      lines.append(f"  {c:18s} " + " / ".join(f"{v:.2f}" for v in q))
  cap = sets[2][1]
  lines.append("special vs capture, median and Mann-Whitney p")
  for c in COLS:
    a, b = sp[c].dropna(), cap[c].dropna()
    lines.append(f"  {c:18s} {a.median():.2f} vs {b.median():.2f}  "
                 f"p {mannwhitneyu(a, b).pvalue:.2f}")
  print("\n".join(lines))
  OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
