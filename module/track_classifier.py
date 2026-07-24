"""Hand-feature classifier over Hough candidate segments, trained on
manual labels from module/server/labeling.py.

Lives at module/ (not module/server/) because it has two consumers:
uncertainty-sampling review (label_uncertain in labeling.py -- once
a classifier is trustworthy enough to rank segments by how unsure it
is, reviewing the LOW-confidence ones is far more informative per
click than reviewing in longest-first order) and
module.matlab_export.remove_unaligned_noise_v2 (the same classifier
used as an actual noise filter in the export pipeline, not just a
review aid). See analysis-note.md 2026-07-18 for the
leave-one-tile-out validation (precision 73-93%, recall 53-96%
depending on held-out tile) that justified building this.

Deliberately NOT the raw-pixel CNN track (e07-ml-binary-segmentation):
these are 6 interpretable features computed over an ALREADY-DETECTED
Hough candidate, not a dense per-pixel classifier learning shape from
scratch -- far more label-efficient at the few-hundred-example scale
we have so far (same analysis-note entry: the CNN still shows
brightness-shortcut behaviour at this data volume, this classifier
does not).
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from module.reader import load_spng
from module.pipeline import find_tracks
from module.pipeline.finder import (
  _measure_tracks, _GRAIN_RADIUS, _footprint_width,
)
from module.preprocess import preprocess

FEATURE_NAMES = [
  "length_px", "n_grains", "footprint_w_px", "mean_intens",
  "cov_frac", "max_gap_px",
]
_COVERAGE_RADIUS_PX = 2
# footprint_w_px replaces the old Track.width_px (std-dev of nearby
# grain-centroid perpendicular offsets -- unstable at low n_grains,
# measured to have ~no track/junk separation, see analysis-note.md
# 2026-07-21). This instead measures the binary mask's own
# cross-sectional thickness directly, which does separate the
# classes (~1.45um median for TRACK vs ~1.74um for JUNK at the
# 0.29um/px E07 scale).


@dataclass
class LiteTrack:
  """Bare-minimum stand-in for pipeline.track.Track, for callers (like
  matlab_export.remove_unaligned_noise_v2) that already have a binary
  mask + fog-removed image in hand and don't want find_tracks's I/O
  and stage-coordinate overhead just to score candidates."""
  px1: int
  py1: int
  px2: int
  py2: int
  length_px: float
  n_grains: int = 0
  width_px: float = 0.0
  mean_intens: float = 0.0


def detect_lite_tracks(
  binary: np.ndarray, fog_img: np.ndarray,
  hough_thr: int, hough_min_line: int, hough_max_gap: int,
  grain_radius: float = _GRAIN_RADIUS,
) -> list[LiteTrack]:
  """Same cv2.HoughLinesP detector as pipeline.finder.find_tracks, but
  working directly from an already-computed binary/fog pair (no
  SpngReader I/O, no repeated preprocessing) -- for use inside a
  per-slice export loop that already has both in hand."""
  lines = cv2.HoughLinesP(
    binary, 1, np.pi / 180, threshold=hough_thr,
    minLineLength=hough_min_line, maxLineGap=hough_max_gap,
  )
  if lines is None:
    return []
  line_arr = lines.reshape(-1, 4)
  measurements = _measure_tracks(fog_img, binary, line_arr, grain_radius)
  tracks = []
  for (x1, y1, x2, y2), (n_g, wid, intens) in zip(line_arr, measurements):
    length = float(np.hypot(x2 - x1, y2 - y1))
    tracks.append(LiteTrack(
      px1=int(x1), py1=int(y1), px2=int(x2), py2=int(y2),
      length_px=length, n_grains=n_g, width_px=wid, mean_intens=intens,
    ))
  return tracks


def _dilated_binary(binary: np.ndarray, radius: int = _COVERAGE_RADIUS_PX):
  k = cv2.getStructuringElement(
    cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
  return cv2.dilate(binary, k)


def extract_features(tracks: list, binary: np.ndarray) -> np.ndarray:
  """Vectorized per-segment features: sample the segment's own line
  at ~1px steps against a pre-dilated binary mask (single fancy-index
  lookup per segment, not a per-point slice+any() loop -- this is
  what makes it fast enough to score thousands of segments live)."""
  dilated = _dilated_binary(binary) > 0
  h, w = binary.shape
  feats = np.zeros((len(tracks), len(FEATURE_NAMES)), dtype=np.float64)
  for i, t in enumerate(tracks):
    n = max(int(t.length_px), 2)
    xs = np.clip(np.linspace(t.px1, t.px2, n).astype(int), 0, w - 1)
    ys = np.clip(np.linspace(t.py1, t.py2, n).astype(int), 0, h - 1)
    covered = dilated[ys, xs]
    cov_frac = covered.mean()
    gap_lengths, run = [], 0
    for c in covered:
      if not c:
        run += 1
      else:
        if run > 0:
          gap_lengths.append(run)
        run = 0
    if run > 0:
      gap_lengths.append(run)
    step_px = t.length_px / n
    max_gap = (max(gap_lengths) if gap_lengths else 0) * step_px
    footprint_w = _footprint_width(t, binary)
    feats[i] = [t.length_px, t.n_grains, footprint_w, t.mean_intens,
                cov_frac, max_gap]
  return feats


def _tracks_and_binary(record: dict):
  reader = load_spng(record["json_rel_path"])
  img = reader.read(record["idx"])
  binary = preprocess(
    img, fog_ksize=record["fog_ksize"], noise_amin=record["noise_amin"],
    noise_amax=record["noise_amax"], noise_cmp=record["noise_cmp"],
  )
  tracks = find_tracks(
    reader, record["idx"], view_id=record["json_rel_path"], zpj_half=0,
    fog_ksize=record["fog_ksize"], noise_amin=record["noise_amin"],
    noise_amax=record["noise_amax"], noise_cmp=record["noise_cmp"],
    hough_thr=record["hough_thr"], hough_min_line=record["hough_min_line"],
    hough_max_gap=record["hough_max_gap"],
  )
  tracks.sort(key=lambda t: t.length_px, reverse=True)
  return tracks, binary


def build_training_set(labels_dir: Path):
  """Return (X, y) from every decision across every label file."""
  X_all, y_all = [], []
  for path in sorted(glob.glob(os.path.join(str(labels_dir), "*.json"))):
    record = json.loads(Path(path).read_text())
    if not record.get("decisions"):
      continue
    tracks, binary = _tracks_and_binary(record)
    feats = extract_features(tracks, binary)
    for seg_id_str, is_track in record["decisions"].items():
      seg_id = int(seg_id_str)
      if not (1 <= seg_id <= len(tracks)):
        continue
      X_all.append(feats[seg_id - 1])
      y_all.append(1 if is_track else 0)
  if not X_all:
    return np.empty((0, len(FEATURE_NAMES))), np.empty((0,))
  return np.array(X_all), np.array(y_all)


def train_classifier(X: np.ndarray, y: np.ndarray):
  """Fit a scaled logistic regression. Returns None if there aren't
  enough examples of both classes to fit anything meaningful."""
  if len(y) < 20 or len(set(y.tolist())) < 2:
    return None
  from sklearn.linear_model import LogisticRegression
  from sklearn.pipeline import make_pipeline
  from sklearn.preprocessing import StandardScaler
  clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
  clf.fit(X, y)
  return clf


CONF_HIGH = 0.9   # predict_proba >= this -> confident "track"
CONF_LOW = 0.1    # predict_proba <= this -> confident "junk"
# Rule-based inconsistency thresholds for flagging a confident
# verdict as worth a human spot-check, not ground truth by
# themselves -- see analysis-note.md 2026-07-22/23 (pseudo-label
# triage: an AI-only visual pass on these was unreliable, a human
# expert pass found 37/38 flagged "long junk" cases were correctly
# junk and 1/38 was a correct track with an imprecise angle fit).
_TRACK_NGRAINS_MED = 4.0
_TRACK_FOOTPRINT_MED = 5.0
_JUNK_LEN_SUSPECT_PX = 150.0


def verdict_for(prob: float) -> str | None:
  """"track"/"junk" for a confident prediction, else None (too
  ambiguous to pseudo-label -- left unreviewed/ignored)."""
  if prob >= CONF_HIGH:
    return "track"
  if prob <= CONF_LOW:
    return "junk"
  return None


def flag_suspicious(verdict: str, feat_row: np.ndarray) -> str:
  """Return a reason string if a confident verdict looks inconsistent
  with its own features (worth a human spot-check), else ''."""
  length_px, n_grains, footprint_w, mean_intens, cov_frac, max_gap = feat_row
  if verdict == "track" and (n_grains < _TRACK_NGRAINS_MED / 2
                              or footprint_w < _TRACK_FOOTPRINT_MED / 2):
    return f"low n_grains={n_grains}/footprint={footprint_w:.1f} for a 'track'"
  if verdict == "junk" and length_px > _JUNK_LEN_SUSPECT_PX:
    return f"long ({length_px:.0f}px) for a 'junk'"
  return ""
