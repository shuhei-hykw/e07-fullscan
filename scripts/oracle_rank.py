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

  python scripts/oracle_rank.py [--set v26_embed_nagara_dz4]
  # -> results/sim_eval/oracle_<set>.txt
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
  d = f.merge(lab.drop(columns=["view"], errors="ignore"), on=KEY,
              how="inner", validate="1:1")
  if len(d) != len(f):
    raise SystemExit(f"{feat_set}: {len(f) - len(d)} rows lack labels")
  d["is_a"] = (d.source == "A").astype(float)
  d["dist_other_um"] = d.dist_other_um.clip(upper=DIST_CAP_UM)
  return d.reset_index(drop=True)


def models():
  return {"hgb": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, class_weight="balanced",
            random_state=SEED),
          "logit": make_pipeline(StandardScaler(), LogisticRegression(
            max_iter=2000, class_weight="balanced"))}


def xmat(d, fill):
  return d[FEATURES].fillna(fill).to_numpy() if fill is not None \
    else d[FEATURES].to_numpy()


def capture_at_k(d, score, lab):
  rk = d.assign(s=score).groupby("event").s.rank(ascending=False,
                                                 method="first")
  best = rk.where(d[lab]).groupby(d.event).min()
  best = best.reindex(sorted(d.event.unique())).fillna(np.inf)
  return best.to_numpy()


def main():
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("--set", default="v26_embed_nagara_dz4")
  args = ap.parse_args()
  emb = load(args.set, f"{args.set}_emb.parquet")
  real = load(REAL_FEATURES[args.set], f"{args.set}_real.parquet")
  events = np.array(sorted(emb.event.unique()))
  if set(real.event) != set(events):
    raise SystemExit("embedded and real event sets differ")
  fill = emb[FEATURES].median()
  lines = [f"{args.set}: {len(events)} events, union {len(emb)} emb / "
           f"{len(real)} real rows (A + B' top {B_TOP}); features "
           + ", ".join(FEATURES)]
  folds = list(GroupKFold(N_FOLDS).split(emb, groups=emb.event))
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
    for name, base in models().items():
      for variant in ("", "+realneg"):
        se, sr = np.zeros(len(emb)), np.zeros(len(real))
        nf = None if name == "hgb" else fill
        for tr, te in folds:
          ev_te = set(emb.event.iloc[te])
          te_r = real.event.isin(ev_te).to_numpy()
          x, y = xmat(emb.iloc[tr], nf), emb[lab].iloc[tr].to_numpy()
          if variant:
            rr = real[~te_r]
            x = np.vstack([x, xmat(rr, nf)])
            y = np.concatenate([y, np.zeros(len(rr), bool)])
          m = models()[name].fit(x, y)
          se[te] = m.predict_proba(xmat(emb.iloc[te], nf))[:, 1]
          sr[te_r] = m.predict_proba(xmat(real[te_r], nf))[:, 1]
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
  out = SIM / f"oracle_{args.set}.txt"
  print("\n".join(lines))
  out.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
  main()
