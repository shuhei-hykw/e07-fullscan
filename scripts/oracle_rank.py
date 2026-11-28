"""Oracle ranker: how well can any score built from the review features
rank sim Xi capture points, when trained on the sim truth itself?

Data: the v26 embedded set (captures rendered into real background) and
its real-background twin, with labels from e07-g4-hypernuclei
data/union_audit/simlabels.py (any candidate within 6 / 12 um of the
capture, developed space). Union cut: all A, B' with dark_rank_view <=
B_TOP. Each event is one view.

Models (HistGradientBoosting, logistic) are trained per label radius
with GroupKFold by event; each fold's model scores its held-out
embedded events and the same events of the real twin, so the real
side gives the chance level at the same capture positions. Capture at
K = fraction of events with a labelled candidate in the top K; net =
embedded - real. Darkness and n_tracks_max are the references.

Leak guards (peer candrank): no edge_px, slice or dark_rank_view
features; the far-region adversarial AUC (embedded vs real candidates
more than FAR_UM from the capture) must stay near 0.5. Variant
"+realneg" adds the real twin's union candidates as negatives.

With --twoview the data are the two-view sets TWOVIEW (both sides A
and B, emb vs _real), each side of an event ranked as its own view;
the peer simlabels then carry presence columns (other view within
12 um, after the pair offset), which are added as PRESENCE features,
and the folds are grouped by background view pair (view_a), since
some pairs share views.

  python scripts/oracle_rank.py [--set v26_embed_nagara_dz4]
  python scripts/oracle_rank.py --twoview
  # -> results/sim_eval/oracle_<set>.txt / oracle_twoview.txt
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

REPO = Path(__file__).resolve().parents[1]
SIM = REPO / "results/sim_eval"
LABELS = REPO.parent / "e07-g4-hypernuclei/output/simlabels"
REAL_FEATURES = {"v26_embed_nagara_dz4": "v19_bgonly_nagara_dz4"}
KEY = ["event", "source", "cand_id"]
FEATURES = ["n_tracks_max", "n_slices", "mean_intens", "angle_spread_best",
            "angle_spread_max", "darkness", "z_span_um", "dist_other_um",
            "mult", "n_bp_20px", "is_a"]
TWOVIEW = [f"twoview_v26_{n}_{s}" for n in ("nagara30", "nagara80")
           for s in ("A", "B")]
PRESENCE = ["present_dz15", "present_dz30", "d_other_um", "in_overlap"]
PRESENT_BONUS = 10.0   # present first, then darkness
B_TOP = 770
DIST_CAP_UM = 1000.0   # dist_other_um is inf when alone
FAR_UM = 200.0
KS = (1, 2, 4, 8, 16, 64, 256, 1024)
N_FOLDS = 5
N_BOOT = 2000
CI = (2.5, 97.5)
SEED = 20261127
RADII = ("6um", "12um")


def load(feat_set, label_file):
  f = pd.read_parquet(SIM / f"{feat_set}_features.parquet")
  f = f[(f.source == "A") | (f.dark_rank_view <= B_TOP)]
  lab = pd.read_parquet(LABELS / label_file)
  lab = lab.drop(columns=["view", "in_pool"], errors="ignore")
  d = f.merge(lab, on=KEY,
              how="inner", validate="1:1")
  if len(d) != len(f):
    raise SystemExit(f"{feat_set}: {len(f) - len(d)} rows lack labels")
  d["is_a"] = (d.source == "A").astype(float)
  d["dist_other_um"] = d.dist_other_um.clip(upper=DIST_CAP_UM)
  if "d_other_um" in d:
    d["d_other_um"] = d.d_other_um.clip(upper=DIST_CAP_UM)
    for c in PRESENCE:
      d[c] = d[c].astype(float)
  d["group"] = d.view_a if "view_a" in d else d.event
  return d.reset_index(drop=True)


def load_parts(parts):
  """Concatenate (features set, label file, tag) parts; event -> tag/ev."""
  out = []
  for feat_set, label_file, tag in parts:
    d = load(feat_set, label_file)
    d["event"] = tag + "/" + d.event
    out.append(d)
  return pd.concat(out, ignore_index=True)


def models():
  return {"hgb": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, class_weight="balanced",
            random_state=SEED),
          "logit": make_pipeline(StandardScaler(), LogisticRegression(
            max_iter=2000, class_weight="balanced"))}


def xmat(d, fill, feats):
  return d[feats].fillna(fill).to_numpy() if fill is not None \
    else d[feats].to_numpy()


def capture_at_k(d, score, lab):
  rk = d.assign(s=score).groupby("event").s.rank(ascending=False,
                                                 method="first")
  best = rk.where(d[lab]).groupby(d.event).min()
  best = best.reindex(sorted(d.event.unique())).fillna(np.inf)
  return best.to_numpy()


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("--set", default="v26_embed_nagara_dz4")
  ap.add_argument("--twoview", action="store_true")
  args = ap.parse_args()
  if args.twoview:
    name, feats = "twoview", FEATURES + PRESENCE
    emb = load_parts([(t, f"{t}_emb.parquet", t) for t in TWOVIEW])
    real = load_parts([(f"{t}_real", f"{t}_real.parquet", t)
                       for t in TWOVIEW])
  else:
    name, feats = args.set, FEATURES
    emb = load(args.set, f"{args.set}_emb.parquet")
    real = load(REAL_FEATURES[args.set], f"{args.set}_real.parquet")
  events = np.array(sorted(emb.event.unique()))
  if set(real.event) != set(events):
    raise SystemExit("embedded and real event sets differ")
  fill = emb[feats].median()
  lines = [f"{name}: {len(events)} views, union {len(emb)} emb / "
           f"{len(real)} real rows (A + B' top {B_TOP}); features "
           + ", ".join(feats)]
  folds = list(GroupKFold(N_FOLDS).split(emb, groups=emb.group))
  boot = np.random.default_rng(SEED).integers(
    0, len(events), size=(N_BOOT, len(events)))
  for r in RADII:
    lab = f"is_capture_{r}"
    lines.append(f"\nlabel {lab}: positives emb {int(emb[lab].sum())} "
                 f"real {int(real[lab].sum())}; capture at K = "
                 + "/".join(map(str, KS)))
    scores = {"darkness": (emb.darkness.fillna(-np.inf).to_numpy(),
                           real.darkness.fillna(-np.inf).to_numpy()),
              "n_tracks_max": (emb.n_tracks_max.fillna(0).to_numpy(),
                               real.n_tracks_max.fillna(0).to_numpy())}
    if "present_dz30" in emb:
      scores["present_first"] = tuple(
        t.present_dz30.to_numpy() * PRESENT_BONUS
        + t.darkness.rank(pct=True).fillna(0).to_numpy()
        for t in (emb, real))
    for name, base in models().items():
      for variant in ("", "+realneg"):
        se, sr = np.zeros(len(emb)), np.zeros(len(real))
        nf = None if name == "hgb" else fill
        for tr, te in folds:
          ev_te = set(emb.event.iloc[te])
          te_r = real.event.isin(ev_te).to_numpy()
          x, y = xmat(emb.iloc[tr], nf, feats), emb[lab].iloc[tr].to_numpy()
          if variant:
            rr = real[~te_r]
            x = np.vstack([x, xmat(rr, nf, feats)])
            y = np.concatenate([y, np.zeros(len(rr), bool)])
          m = models()[name].fit(x, y)
          se[te] = m.predict_proba(xmat(emb.iloc[te], nf, feats))[:, 1]
          sr[te_r] = m.predict_proba(xmat(real[te_r], nf, feats))[:, 1]
        scores[f"oracle_{name}{variant}"] = (se, sr)
    best = {}
    for name, (se, sr) in scores.items():
      be = capture_at_k(emb, se, lab)
      br = capture_at_k(real, sr, lab)
      best[name] = (be, br)
      far_e = emb.d_cap.to_numpy() > FAR_UM
      far_r = real.d_cap.to_numpy() > FAR_UM
      auc = roc_auc_score(np.r_[np.ones(far_e.sum()), np.zeros(far_r.sum())],
                          np.r_[se[far_e], sr[far_r]])
      lines.append(f"  {name:22s} far-AUC {auc:.2f}")
      for tag, b in (("emb", be), ("real", br)):
        lines.append(f"    {tag:4s} " + " ".join(
          f"{(b <= k).mean():.2f}" for k in KS))
      net = [(be <= k).mean() - (br <= k).mean() for k in KS]
      lines.append("    net  " + " ".join(f"{v:+.2f}" for v in net))
    lines.append("  net pool ceiling (any candidate): "
                 f"{np.isfinite(best['darkness'][0]).mean() - np.isfinite(best['darkness'][1]).mean():+.2f}")
    lines.append(f"  paired bootstrap over events ({N_BOOT}), net "
                 f"difference [{CI[0]:g}, {CI[1]:g}] %")
    for a in ("oracle_hgb", "oracle_logit"):
      row = [f"    {a} - darkness:"]
      for k in (16, 64, 256):
        diff = []
        for s in (a, "darkness"):
          be, br = best[s]
          diff.append((be <= k).astype(float) - (br <= k))
        dd = diff[0] - diff[1]
        lo, hi = np.percentile(dd[boot].mean(axis=1), CI) * 100
        row.append(f"K {k} {dd.mean() * 100:+.0f} [{lo:+.0f}, {hi:+.0f}]")
      lines.append("  ".join(row))
  out = SIM / f"oracle_{name}.txt"
  print("\n".join(lines))
  out.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
