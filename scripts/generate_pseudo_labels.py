"""Bulk-generate CNN pseudo-labels from Method A's classifier.

For each target tile: detect Hough segments (production params) ->
cluster (footprint-width quality) -> classify -> rasterize confident
verdicts into a sparse mask (-1 unreviewed, 0 junk, 1 track), same
convention as e07-ml-binary-segmentation/src/real_label_dataset.py,
so the two can be pooled directly by RealLabelDataset(roots=[...]).

Also flags feature-inconsistent confident verdicts
(track_classifier.flag_suspicious) into a review queue -- these are
NOT ground truth corrections, just candidates for a human spot-check
(see analysis-note.md 2026-07-22/23: an AI-only visual pass on these
was unreliable, don't trust this tool's own judgment over a human's).

Usage:
  python scripts/generate_pseudo_labels.py --tile-list tiles.txt
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.reader import load_spng
from module.pipeline import find_tracks
from module.pipeline.cluster import cluster_tracks
from module.preprocess import preprocess
from module import track_classifier

TILE_PREFIX = ("fullscan-image/E07/MOD108/PL12/tohoku-v1/AREA00/"
               "IMAGE00_AREA00")
IDX = 29
HOUGH_THR, HOUGH_ML, HOUGH_MG = 35, 30, 40  # production values
SEG_WIDTH_PX = 4  # matches real_label_dataset.py convention
LABELS_DIR = Path(__file__).resolve().parents[1] / "results" / "manual_labels"
_DEFAULT_OUT_DIR = (
  Path(__file__).resolve().parents[2]
  / "e07-ml-binary-segmentation" / "data" / "pseudo_labels")
_DEFAULT_REVIEW_DIR = (
  Path(__file__).resolve().parents[1] / "results" / "pseudo_label_review")


def _read_with_retry(reader, idx, attempts=3, delay=2.0):
  for i in range(attempts):
    try:
      return reader.read(idx)
    except Exception as e:
      if i == attempts - 1:
        raise
      print(f"  read retry {i+1}/{attempts}: {e}")
      time.sleep(delay)


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--tile-list", required=True,
                   help="text file, one tile .json filename per line")
  ap.add_argument("--out-dir", default=str(_DEFAULT_OUT_DIR))
  ap.add_argument("--review-dir", default=str(_DEFAULT_REVIEW_DIR))
  ap.add_argument("--idx", type=int, default=IDX)
  args = ap.parse_args()

  out_dir = Path(args.out_dir)
  out_dir.mkdir(parents=True, exist_ok=True)
  review_dir = Path(args.review_dir)
  review_dir.mkdir(parents=True, exist_ok=True)

  print("training classifier (footprint_w_px, current manual labels)...")
  X, y = track_classifier.build_training_set(LABELS_DIR)
  clf = track_classifier.train_classifier(X, y)
  if clf is None:
    print("not enough manual labels to train a classifier yet")
    return
  print(f"trained on {len(y)} examples")

  tiles = [ln.strip() for ln in Path(args.tile_list).read_text().splitlines()
           if ln.strip()]
  print(f"{len(tiles)} target tiles")

  flagged = []
  n_ok = n_track_total = n_junk_total = 0
  for fname in tiles:
    json_rel = f"{TILE_PREFIX}/{fname}"
    try:
      reader = load_spng(json_rel)
      px_scale = reader.affine_p2s[0] * 1000.0
      raw_img = _read_with_retry(reader, args.idx)
      binary = preprocess(raw_img, fog_ksize=51, noise_amin=2,
                           noise_amax=100, noise_cmp=50)
      tracks = find_tracks(
        reader, idx=args.idx, view_id=json_rel, px_scale_um=px_scale,
        hough_thr=HOUGH_THR, hough_min_line=HOUGH_ML,
        hough_max_gap=HOUGH_MG)
      clustered = cluster_tracks(tracks, binary=binary)
      if not clustered:
        print(f"{fname}: no segments, skip")
        continue
      feats = track_classifier.extract_features(clustered, binary)
      probs = clf.predict_proba(feats)[:, 1]

      mask = np.full(raw_img.shape, -1, dtype=np.int8)
      n_pos = n_neg = 0
      for t, p, f in zip(clustered, probs, feats):
        verdict = track_classifier.verdict_for(p)
        if verdict is None:
          continue
        if verdict == "track":
          cv2.line(mask, (t.px1, t.py1), (t.px2, t.py2), 1, SEG_WIDTH_PX)
          n_pos += 1
        else:
          layer = np.zeros(raw_img.shape, dtype=np.uint8)
          cv2.line(layer, (t.px1, t.py1), (t.px2, t.py2), 1, SEG_WIDTH_PX)
          mask[(layer > 0) & (mask != 1)] = 0
          n_neg += 1
        reason = track_classifier.flag_suspicious(verdict, f)
        if reason:
          flagged.append({
            "tile": fname, "npz": None, "verdict": verdict,
            "prob": float(p), "px1": t.px1, "py1": t.py1,
            "px2": t.px2, "py2": t.py2, "length_px": float(f[0]),
            "n_grains": int(f[1]), "footprint_w": float(f[2]),
            "reason": reason,
          })

      stem = json_rel.replace("/", "__") + f"__z{args.idx}"
      npz_path = out_dir / f"{stem}.npz"
      np.savez_compressed(npz_path, raw=raw_img, mask=mask)
      for f in flagged:
        if f["tile"] == fname and f["npz"] is None:
          f["npz"] = str(npz_path)
      n_ok += 1
      n_track_total += n_pos
      n_junk_total += n_neg
      print(f"{fname}: raw={len(tracks)} clustered={len(clustered)} "
            f"confident_track={n_pos} confident_junk={n_neg}")
    except Exception as e:
      print(f"{fname}: FAILED ({e})")
      continue

  print(f"\n=== done: {n_ok}/{len(tiles)} tiles pseudo-labeled ===")
  print(f"total confident track segments: {n_track_total}")
  print(f"total confident junk segments: {n_junk_total}")
  print(f"{len(flagged)} segments flagged for human review")

  review_path = review_dir / "flagged.json"
  existing = []
  if review_path.exists():
    existing = json.loads(review_path.read_text())
  review_path.write_text(json.dumps(existing + flagged, indent=2))
  print(f"review queue: {review_path} ({len(existing) + len(flagged)} total)")


if __name__ == "__main__":
  main()
