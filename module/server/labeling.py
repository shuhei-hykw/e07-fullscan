"""Manual review tool: step through Hough-detected candidate track
segments one at a time and mark each true (real track) / false
(junk), to build real (not copy-paste synthetic) ground truth for
e07-ml-binary-segmentation.

Sequential review, not click-on-canvas: a dense image (especially
real E07 tiles, ~2x the foreground density of the E373 KISO
reference, see analysis-note.md 2026-07-15) can have thousands of
Hough candidates, and a long real track is often broken into many
short segments by gaps -- hunting down and precisely clicking each
one on a 2048x2048 canvas is tedious. Instead each segment is cropped
and shown full-screen in turn; the user just answers true/false
(keyboard arrows or buttons) and the tool auto-advances, tracking
progress so a session can be resumed later.

Segments are produced by module.pipeline.finder.find_tracks (the
same cv2.HoughLinesP detector used by the classical noise filter and
the /view/ "trk" overlay), with a large max_gap so gaps in one real
track get merged into a single long candidate rather than many short
fragments. Review order is longest-first: high-purity real tracks up
front is a genuine advantage, not a defect (2026-07-15, user
correction after a same-day attempt to switch to shuffled order --
shuffled surfaced too much obvious junk instead). Merging is not
perfect -- a single physical track can still show up as more than
one segment (e.g. one long merged piece plus a smaller leftover
fragment); that's a known limitation of straight-line Hough
detection on a real (not perfectly straight) track, not a bug to
route around during review -- just judge each one on its own merits.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, render_template_string, request, \
  send_file

from module.reader import load_spng
from module.preprocess import fog_remove
from module.pipeline import find_tracks
from module import track_classifier

_FOG_KSIZE      = 51
_NOISE_AMIN     = 2
_NOISE_AMAX     = 100
_NOISE_CMP      = 50
# Deliberately permissive threshold/min-length (matches
# module.matlab_export's denoise filter, not finder.py's stricter
# find_tracks defaults) so review surfaces plenty of likely-noise
# candidates alongside real tracks. max_gap is set higher than either
# of those, specifically for review: a small gap chops one real track
# into many short fragments, which is more tedious to review and
# gives less context per decision than one longer merged segment.
# Swept 15/20/25/40/60/100 on a real E07 tile (2026-07-15): 60
# quadrupled the longest detected track (264px -> 1308px) with no
# visible false bridging; 100 broke (a 2495px "segment" was a
# straight line drawn through unrelated noise, confirmed visually).
# Dialed back twice after hands-on review feedback (60 -> 40 -> 20,
# same day) -- fewer, cleaner candidates day-to-day even though this
# alone doesn't fully eliminate fragmentation (accepted tradeoff, see
# module docstring). If it still feels too permissive, keep dialing
# down; there was no sign 20 is a hard floor.
_HOUGH_THR      = 8
_HOUGH_ML       = 10
_HOUGH_MG       = 20

_CROP_MARGIN_PX = 100  # context beyond the segment's own bounding box
_CROP_MIN_HALF  = 200  # never show a crop smaller than this (short segs)
_CROP_MAX_HALF  = 350  # never show a crop bigger than this (long segs)
# A short Hough segment is often just a fragment of one longer real
# track broken up by a small gap -- without enough surrounding
# context a genuine long track can look like an isolated fleck. Sized
# generously (2026-07-15, user feedback) rather than tight to the
# segment's own length.
_BG_STRETCH_LO_PCTL = 2.0
_BG_STRETCH_HI_PCTL = 99.5
_SEG_COLOR_BGR  = (60, 40, 235)  # highlight colour for the reviewed segment

# Tiles mixed together in /label_mix, spread across the AREA00 grid
# (not clustered near each other) for illumination/density diversity.
# A classifier trained on a single tile's labels learned that tile's
# own brightness pattern instead of real track shape (2026-07-18
# finding, both the CNN and a hand-feature logistic regression) --
# labelling must span multiple tiles to catch that during training,
# not just at final eval. idx=29 (mid-stack) for all, matching the
# original single-tile session.
_MULTI_TILE_PREFIX = (
  "fullscan-image/E07/MOD108/PL12/tohoku-v1/AREA00/IMAGE00_AREA00")
_MULTI_TILE_SOURCES = [
  (f"{_MULTI_TILE_PREFIX}/V00001012_L0_VX0022_VY0022_0_058.json", 29),
  (f"{_MULTI_TILE_PREFIX}/V00000011_L0_VX0011_VY0000_0_058.json", 29),
  (f"{_MULTI_TILE_PREFIX}/V00001339_L0_VX0034_VY0029_0_058.json", 29),
  (f"{_MULTI_TILE_PREFIX}/V00000991_L0_VX0001_VY0022_0_058.json", 29),
]


def _hough_params(request) -> dict:
  g = request.args.get
  def i(name, default):
    try:
      return int(g(name, default))
    except (ValueError, TypeError):
      return int(default)
  return dict(
    hough_thr=i("hough_thr", _HOUGH_THR),
    hough_min_line=i("hough_ml", _HOUGH_ML),
    hough_max_gap=i("hough_mg", _HOUGH_MG),
  )


def _segments(json_path: Path, idx: int, hough_params: dict):
  """Return (raw_img, fog_img, tracks) for one slice, sorted
  longest-first.

  Tried switching this to a shuffled order on 2026-07-15 after
  feedback that longest-first "mostly looks like clean tracks" --
  reverted the same day: the user clarified high track purity is a
  feature (reviewing obviously-real long tracks first is fine), and
  a shuffle just surfaced a junk-heavy sample instead. Keep
  longest-first.
  """
  reader = load_spng(json_path)
  raw_img = reader.read(idx)
  fog_img = fog_remove(raw_img, _FOG_KSIZE)
  tracks = find_tracks(
    reader, idx,
    view_id=str(json_path), zpj_half=0, fog_ksize=_FOG_KSIZE,
    noise_amin=_NOISE_AMIN, noise_amax=_NOISE_AMAX,
    noise_cmp=_NOISE_CMP, **hough_params,
  )
  tracks.sort(key=lambda t: t.length_px, reverse=True)
  return raw_img, fog_img, tracks


def _stretch(img: np.ndarray) -> np.ndarray:
  lo, hi = np.percentile(img, [_BG_STRETCH_LO_PCTL, _BG_STRETCH_HI_PCTL])
  norm = np.clip((img.astype(np.float64) - lo) / max(hi - lo, 1e-6), 0, 1)
  return (norm * 255).astype(np.uint8)


_PANEL_GAP_PX = 6  # separator width between the raw/highlighted panels


def _segment_crop_png(raw_img: np.ndarray, fog_img: np.ndarray, t) -> bytes:
  """Three panels side by side: raw (unprocessed -- what the ML
  track actually trains on, 2026-07-18 user request), plain
  fog-removed (easier to judge by eye), and fog-removed with the
  segment highlighted (semi-transparent, so the underlying grain
  pattern stays visible under the line too -- 2026-07-15 feedback)."""
  h, w = fog_img.shape
  cx = (t.px1 + t.px2) / 2
  cy = (t.py1 + t.py2) / 2
  half = np.clip(
    t.length_px / 2 + _CROP_MARGIN_PX, _CROP_MIN_HALF, _CROP_MAX_HALF)
  x0 = int(max(0, cx - half)); x1 = int(min(w, cx + half))
  y0 = int(max(0, cy - half)); y1 = int(min(h, cy + half))
  raw = cv2.cvtColor(_stretch(raw_img[y0:y1, x0:x1]), cv2.COLOR_GRAY2BGR)
  plain = cv2.cvtColor(_stretch(fog_img[y0:y1, x0:x1]), cv2.COLOR_GRAY2BGR)
  line_layer = plain.copy()
  cv2.line(line_layer, (t.px1 - x0, t.py1 - y0), (t.px2 - x0, t.py2 - y0),
            _SEG_COLOR_BGR, 4, lineType=cv2.LINE_AA)
  highlighted = cv2.addWeighted(line_layer, 0.55, plain, 0.45, 0)
  gap = np.full((plain.shape[0], _PANEL_GAP_PX, 3), 40, dtype=np.uint8)
  combined = np.hstack([raw, gap, plain, gap, highlighted])
  _, buf = cv2.imencode(".png", combined)
  return buf.tobytes()


def register_labeling_routes(app: Flask, safe_resolve, labels_dir: Path):
  labels_dir.mkdir(parents=True, exist_ok=True)

  def _label_file(json_rel_path: str, idx: int) -> Path:
    safe_name = json_rel_path.replace("/", "__")
    return labels_dir / f"{safe_name}__z{idx}.json"

  def _load_record(json_rel_path: str, idx: int) -> dict:
    p = _label_file(json_rel_path, idx)
    if p.exists():
      return json.loads(p.read_text())
    return {"decisions": {}}

  @app.route("/label/<path:json_rel_path>/<int:idx>")
  def label_page(json_rel_path: str, idx: int) -> str:
    hp = _hough_params(request)
    return render_template_string(
      _LABEL_TEMPLATE, json_rel_path=json_rel_path, idx=idx,
      hough_thr=hp["hough_thr"], hough_ml=hp["hough_min_line"],
      hough_mg=hp["hough_max_gap"],
    )

  @app.route("/label_mix")
  def label_mix_page() -> str:
    hp = _hough_params(request)
    return render_template_string(
      _LABEL_MIX_TEMPLATE,
      sources=[{"path": p, "idx": i} for p, i in _MULTI_TILE_SOURCES],
      hough_thr=hp["hough_thr"], hough_ml=hp["hough_min_line"],
      hough_mg=hp["hough_max_gap"],
    )

  @app.route("/label_mix_segments")
  def label_mix_segments():
    hp = _hough_params(request)
    out = []
    for json_rel_path, idx in _MULTI_TILE_SOURCES:
      try:
        _, _, tracks = _segments(safe_resolve(json_rel_path), idx, hp)
        out.append({"path": json_rel_path, "idx": idx, "n": len(tracks)})
      except Exception as e:
        out.append({"path": json_rel_path, "idx": idx, "n": 0,
                     "error": str(e)})
    return jsonify(out)

  @app.route("/label_uncertain")
  def label_uncertain_page() -> str:
    hp = _hough_params(request)
    return render_template_string(
      _LABEL_UNCERTAIN_TEMPLATE,
      hough_thr=hp["hough_thr"], hough_ml=hp["hough_min_line"],
      hough_mg=hp["hough_max_gap"],
    )

  @app.route("/label_uncertain_segments")
  def label_uncertain_segments():
    """Rank undecided segments across _MULTI_TILE_SOURCES by how
    unsure the current classifier is (|prob-0.5| ascending) --
    uncertainty sampling: a click here is more informative than one
    more longest-first click the classifier already agrees with."""
    hp = _hough_params(request)
    X, y = track_classifier.build_training_set(labels_dir)
    clf = track_classifier.train_classifier(X, y)
    if clf is None:
      return jsonify({
        "error": "not enough labelled data yet to train a classifier "
                 "(need >=20 decisions with both true and false)",
        "n_labelled": len(y),
      }), 400

    scored = []
    for json_rel_path, idx in _MULTI_TILE_SOURCES:
      try:
        record = dict(
          json_rel_path=json_rel_path, idx=idx,
          fog_ksize=_FOG_KSIZE, noise_amin=_NOISE_AMIN,
          noise_amax=_NOISE_AMAX, noise_cmp=_NOISE_CMP, **hp,
        )
        tracks, binary = track_classifier._tracks_and_binary(record)
        decided = set(int(k) for k in
                       _load_record(json_rel_path, idx)["decisions"])
        feats = track_classifier.extract_features(tracks, binary)
        probs = clf.predict_proba(feats)[:, 1]
        for seg_id, prob in enumerate(probs, start=1):
          if seg_id in decided:
            continue
          scored.append({
            "path": json_rel_path, "idx": idx, "id": seg_id,
            "prob": round(float(prob), 3),
            "uncertainty": round(1.0 - abs(float(prob) - 0.5) * 2, 3),
          })
      except Exception as e:
        return jsonify({"error": f"{json_rel_path}: {e}"}), 500

    scored.sort(key=lambda s: -s["uncertainty"])
    return jsonify({"n_labelled": len(y), "items": scored[:1000]})

  @app.route("/label_segments/<path:json_rel_path>/<int:idx>")
  def label_segments(json_rel_path: str, idx: int):
    try:
      _, _, tracks = _segments(
        safe_resolve(json_rel_path), idx, _hough_params(request))
      return jsonify({"n": len(tracks), "lengths_px": [
        round(t.length_px, 1) for t in tracks
      ]})
    except Exception as e:
      return jsonify({"error": str(e)}), 500

  @app.route(
    "/label_segment_crop/<path:json_rel_path>/<int:idx>/<int:seg_id>")
  def label_segment_crop(json_rel_path: str, idx: int, seg_id: int):
    try:
      raw_img, fog_img, tracks = _segments(
        safe_resolve(json_rel_path), idx, _hough_params(request))
      if not (1 <= seg_id <= len(tracks)):
        return "segment id out of range", 404
      png = _segment_crop_png(raw_img, fog_img, tracks[seg_id - 1])
      return send_file(io.BytesIO(png), mimetype="image/png")
    except Exception as e:
      return str(e), 500

  @app.route("/label_decide/<path:json_rel_path>/<int:idx>",
             methods=["POST"])
  def label_decide(json_rel_path: str, idx: int):
    try:
      payload = request.get_json(force=True)
      seg_id = str(int(payload["id"]))
      decision = bool(payload["decision"])
      hp = _hough_params(request)
      record = _load_record(json_rel_path, idx)
      record["decisions"][seg_id] = decision
      record.update({
        "json_rel_path": json_rel_path,
        "idx": idx,
        "fog_ksize": _FOG_KSIZE,
        "noise_amin": _NOISE_AMIN,
        "noise_amax": _NOISE_AMAX,
        "noise_cmp": _NOISE_CMP,
        "hough_thr": hp["hough_thr"],
        "hough_min_line": hp["hough_min_line"],
        "hough_max_gap": hp["hough_max_gap"],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
      })
      _label_file(json_rel_path, idx).write_text(
        json.dumps(record, indent=2))
      n_true = sum(1 for v in record["decisions"].values() if v)
      return jsonify({"ok": True, "n_decided": len(record["decisions"]),
                       "n_true": n_true})
    except Exception as e:
      return jsonify({"ok": False, "error": str(e)}), 500

  @app.route("/label_load/<path:json_rel_path>/<int:idx>")
  def label_load(json_rel_path: str, idx: int):
    return jsonify(_load_record(json_rel_path, idx))


_LABEL_TEMPLATE = """
<html>
<head>
<title>Review: {{ json_rel_path }} z={{ idx }}</title>
<style>
  body { background:#141414; color:#ddd; font-family:sans-serif;
         margin:0; padding:20px; display:flex; flex-direction:column;
         align-items:center; }
  #bar { width:100%; max-width:96vw; display:flex;
         justify-content:space-between; font-family:monospace;
         font-size:0.9em; color:#aaa; margin-bottom:10px; }
  #progress { width:100%; max-width:96vw; height:6px; background:#333;
              border-radius:3px; overflow:hidden; margin-bottom:16px; }
  #progress-fill { height:100%; background:#5fd0c4; width:0%; }
  #crop-wrap { border:1px solid #333; border-radius:6px;
               overflow:hidden; line-height:0; }
  #crop { max-width:96vw; max-height:66vh; image-rendering:pixelated; }
  #controls { display:flex; gap:16px; margin-top:18px; }
  button { background:#2a2a2a; color:#ddd; border:1px solid #555;
           padding:14px 28px; border-radius:6px; cursor:pointer;
           font-size:1.05em; }
  #btn-false { border-color:#a44; }
  #btn-false:hover { background:#3a2222; }
  #btn-true { border-color:#4a8; }
  #btn-true:hover { background:#223a2c; }
  #hint { color:#777; font-size:0.82em; margin-top:10px; text-align:center; }
  #done { font-size:1.3em; color:#5fd0c4; margin-top:40px; }
</style>
</head>
<body>
  <div id="bar">
    <span id="counter">loading...</span>
    <span id="stats"></span>
  </div>
  <div id="progress"><div id="progress-fill"></div></div>
  <div id="crop-wrap"><img id="crop" src="" alt="segment crop"></div>
  <div id="controls">
    <button id="btn-false" onclick="decide(false)">&larr; Junk</button>
    <button id="btn-true" onclick="decide(true)">Track &rarr;</button>
  </div>
  <div id="hint">&larr; / F = junk &nbsp;&nbsp; &rarr; / J = track
    &nbsp;&nbsp; Backspace = undo last</div>
  <div id="done" style="display:none">All segments reviewed.</div>
<script>
const jsonRelPath = {{ json_rel_path | tojson }};
const idx = {{ idx }};
const houghQS = "hough_thr={{ hough_thr }}&hough_ml={{ hough_ml }}"
  + "&hough_mg={{ hough_mg }}";

let total = 0, decisions = {}, order = [], pos = 0, history = [];

const counter = document.getElementById('counter');
const stats = document.getElementById('stats');
const fill = document.getElementById('progress-fill');
const cropImg = document.getElementById('crop');
const doneEl = document.getElementById('done');
const controls = document.getElementById('controls');

function updateStats() {
  const nTrue = Object.values(decisions).filter(v => v === true).length;
  const nFalse = Object.values(decisions).filter(v => v === false).length;
  stats.textContent = `track: ${nTrue}   junk: ${nFalse}`;
}

function showCurrent() {
  if (pos >= order.length) {
    cropImg.style.display = 'none';
    controls.style.display = 'none';
    doneEl.style.display = 'block';
    counter.textContent = `${order.length} / ${total} reviewed`;
    return;
  }
  const segId = order[pos];
  counter.textContent = `${pos + 1} / ${order.length} (segment #${segId})`;
  fill.style.width = `${100 * pos / order.length}%`;
  cropImg.src =
    `/label_segment_crop/${jsonRelPath}/${idx}/${segId}?${houghQS}`
    + `&_=${Date.now()}`;
}

async function decide(value) {
  if (pos >= order.length) return;
  const segId = order[pos];
  history.push(segId);
  decisions[segId] = value;
  updateStats();
  pos++;
  showCurrent();
  await fetch(`/label_decide/${jsonRelPath}/${idx}?${houghQS}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: segId, decision: value}),
  });
}

function undo() {
  if (history.length === 0) return;
  const segId = history.pop();
  delete decisions[segId];
  pos = order.indexOf(segId);
  updateStats();
  showCurrent();
}

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'ArrowLeft' || ev.key.toLowerCase() === 'f') decide(false);
  else if (ev.key === 'ArrowRight' || ev.key.toLowerCase() === 'j') decide(true);
  else if (ev.key === 'Backspace') undo();
});

async function init() {
  const segRes = await (await fetch(
    `/label_segments/${jsonRelPath}/${idx}?${houghQS}`)).json();
  total = segRes.n || 0;
  order = Array.from({length: total}, (_, i) => i + 1);

  const saved = await (await fetch(
    `/label_load/${jsonRelPath}/${idx}`)).json();
  decisions = {};
  for (const [k, v] of Object.entries(saved.decisions || {})) {
    decisions[parseInt(k)] = v;
  }
  updateStats();
  // resume at the first undecided segment (longest-first order)
  pos = order.findIndex(id => !(id in decisions));
  if (pos === -1) pos = order.length;
  showCurrent();
}

init();
</script>
</body>
</html>
"""


_LABEL_MIX_TEMPLATE = """
<html>
<head>
<title>Review (mixed tiles)</title>
<style>
  body { background:#141414; color:#ddd; font-family:sans-serif;
         margin:0; padding:20px; display:flex; flex-direction:column;
         align-items:center; }
  #bar { width:100%; max-width:96vw; display:flex;
         justify-content:space-between; font-family:monospace;
         font-size:0.9em; color:#aaa; margin-bottom:10px; }
  #progress { width:100%; max-width:96vw; height:6px; background:#333;
              border-radius:3px; overflow:hidden; margin-bottom:16px; }
  #progress-fill { height:100%; background:#5fd0c4; width:0%; }
  #crop-wrap { border:1px solid #333; border-radius:6px;
               overflow:hidden; line-height:0; }
  #crop { max-width:96vw; max-height:66vh; image-rendering:pixelated; }
  #controls { display:flex; gap:16px; margin-top:18px; }
  button { background:#2a2a2a; color:#ddd; border:1px solid #555;
           padding:14px 28px; border-radius:6px; cursor:pointer;
           font-size:1.05em; }
  #btn-false { border-color:#a44; }
  #btn-false:hover { background:#3a2222; }
  #btn-true { border-color:#4a8; }
  #btn-true:hover { background:#223a2c; }
  #hint { color:#777; font-size:0.82em; margin-top:10px; text-align:center; }
  #done { font-size:1.3em; color:#5fd0c4; margin-top:40px; }
  #tile-name { color:#5fd0c4; }
</style>
</head>
<body>
  <div id="bar">
    <span id="counter">loading...</span>
    <span id="stats"></span>
  </div>
  <div id="progress"><div id="progress-fill"></div></div>
  <div id="crop-wrap"><img id="crop" src="" alt="segment crop"></div>
  <div id="controls">
    <button id="btn-false" onclick="decide(false)">&larr; Junk</button>
    <button id="btn-true" onclick="decide(true)">Track &rarr;</button>
  </div>
  <div id="hint">&larr; / F = junk &nbsp;&nbsp; &rarr; / J = track
    &nbsp;&nbsp; Backspace = undo last &nbsp;&nbsp;
    tile: <span id="tile-name">-</span></div>
  <div id="done" style="display:none">All segments reviewed.</div>
<script>
const sources = {{ sources | tojson }};
const houghQS = "hough_thr={{ hough_thr }}&hough_ml={{ hough_ml }}"
  + "&hough_mg={{ hough_mg }}";

// order: round-robin across sources so a short session still
// touches every tile, not just the first one in the list
// (2026-07-18, user request to mix tiles so training/eval data
// isn't drawn from a single tile's own illumination pattern)
let order = [];       // [{srcIdx, segId}]
let decisions = {};   // key `${srcIdx}:${segId}` -> bool
let pos = 0, history = [];

const counter = document.getElementById('counter');
const stats = document.getElementById('stats');
const fill = document.getElementById('progress-fill');
const cropImg = document.getElementById('crop');
const doneEl = document.getElementById('done');
const controls = document.getElementById('controls');
const tileNameEl = document.getElementById('tile-name');

function key(srcIdx, segId) { return `${srcIdx}:${segId}`; }

function updateStats() {
  const vals = Object.values(decisions);
  const nTrue = vals.filter(v => v === true).length;
  const nFalse = vals.filter(v => v === false).length;
  stats.textContent = `track: ${nTrue}   junk: ${nFalse}`;
}

function showCurrent() {
  if (pos >= order.length) {
    cropImg.style.display = 'none';
    controls.style.display = 'none';
    doneEl.style.display = 'block';
    counter.textContent = `${order.length} / ${order.length} reviewed`;
    return;
  }
  const { srcIdx, segId } = order[pos];
  const src = sources[srcIdx];
  const tileLabel = src.path.split('/').pop();
  counter.textContent =
    `${pos + 1} / ${order.length} (tile ${srcIdx + 1}/${sources.length}, `
    + `segment #${segId})`;
  tileNameEl.textContent = tileLabel;
  fill.style.width = `${100 * pos / order.length}%`;
  cropImg.src =
    `/label_segment_crop/${src.path}/${src.idx}/${segId}?${houghQS}`
    + `&_=${Date.now()}`;
}

async function decide(value) {
  if (pos >= order.length) return;
  const { srcIdx, segId } = order[pos];
  const src = sources[srcIdx];
  history.push({ srcIdx, segId });
  decisions[key(srcIdx, segId)] = value;
  updateStats();
  pos++;
  showCurrent();
  await fetch(`/label_decide/${src.path}/${src.idx}?${houghQS}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: segId, decision: value}),
  });
}

function undo() {
  if (history.length === 0) return;
  const { srcIdx, segId } = history.pop();
  delete decisions[key(srcIdx, segId)];
  pos = order.findIndex(o => o.srcIdx === srcIdx && o.segId === segId);
  updateStats();
  showCurrent();
}

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'ArrowLeft' || ev.key.toLowerCase() === 'f') decide(false);
  else if (ev.key === 'ArrowRight' || ev.key.toLowerCase() === 'j') decide(true);
  else if (ev.key === 'Backspace') undo();
});

async function init() {
  const meta = await (await fetch(
    `/label_mix_segments?${houghQS}`)).json();
  // meta[i].n segments per source, each already longest-first server
  // side; interleave round-robin across sources
  const counts = meta.map(m => m.n);
  const maxN = Math.max(0, ...counts);
  for (let segId = 1; segId <= maxN; segId++) {
    for (let srcIdx = 0; srcIdx < counts.length; srcIdx++) {
      if (segId <= counts[srcIdx]) order.push({ srcIdx, segId });
    }
  }

  decisions = {};
  for (let srcIdx = 0; srcIdx < sources.length; srcIdx++) {
    const src = sources[srcIdx];
    const saved = await (await fetch(
      `/label_load/${src.path}/${src.idx}`)).json();
    for (const [k, v] of Object.entries(saved.decisions || {})) {
      decisions[key(srcIdx, parseInt(k))] = v;
    }
  }
  updateStats();
  pos = order.findIndex(o => !(key(o.srcIdx, o.segId) in decisions));
  if (pos === -1) pos = order.length;
  showCurrent();
}

init();
</script>
</body>
</html>
"""


_LABEL_UNCERTAIN_TEMPLATE = """
<html>
<head>
<title>Review (uncertainty sampling)</title>
<style>
  body { background:#141414; color:#ddd; font-family:sans-serif;
         margin:0; padding:20px; display:flex; flex-direction:column;
         align-items:center; }
  #bar { width:100%; max-width:96vw; display:flex;
         justify-content:space-between; font-family:monospace;
         font-size:0.9em; color:#aaa; margin-bottom:10px; }
  #progress { width:100%; max-width:96vw; height:6px; background:#333;
              border-radius:3px; overflow:hidden; margin-bottom:16px; }
  #progress-fill { height:100%; background:#c48fff; width:0%; }
  #crop-wrap { border:1px solid #333; border-radius:6px;
               overflow:hidden; line-height:0; }
  #crop { max-width:96vw; max-height:66vh; image-rendering:pixelated; }
  #controls { display:flex; gap:16px; margin-top:18px; }
  button { background:#2a2a2a; color:#ddd; border:1px solid #555;
           padding:14px 28px; border-radius:6px; cursor:pointer;
           font-size:1.05em; }
  #btn-false { border-color:#a44; }
  #btn-false:hover { background:#3a2222; }
  #btn-true { border-color:#4a8; }
  #btn-true:hover { background:#223a2c; }
  #hint { color:#777; font-size:0.82em; margin-top:10px; text-align:center; }
  #done { font-size:1.3em; color:#c48fff; margin-top:40px; }
  #err { color:#e88; margin-top:40px; text-align:center;
         max-width:500px; }
  #tile-name { color:#c48fff; }
  #prob { color:#c48fff; }
</style>
</head>
<body>
  <div id="bar">
    <span id="counter">loading...</span>
    <span id="stats"></span>
  </div>
  <div id="progress"><div id="progress-fill"></div></div>
  <div id="crop-wrap"><img id="crop" src="" alt="segment crop"></div>
  <div id="controls">
    <button id="btn-false" onclick="decide(false)">&larr; Junk</button>
    <button id="btn-true" onclick="decide(true)">Track &rarr;</button>
  </div>
  <div id="hint">&larr; / F = junk &nbsp;&nbsp; &rarr; / J = track
    &nbsp;&nbsp; Backspace = undo last &nbsp;&nbsp;
    tile: <span id="tile-name">-</span> &nbsp;&nbsp;
    classifier p(track)=<span id="prob">-</span></div>
  <div id="done" style="display:none">
    All fetched uncertain segments reviewed -- reload to re-rank with
    the classifier retrained on your new decisions.</div>
  <div id="err" style="display:none"></div>
<script>
const houghQS = "hough_thr={{ hough_thr }}&hough_ml={{ hough_ml }}"
  + "&hough_mg={{ hough_mg }}";

// Snapshot ranking, not live re-ranking: the classifier is trained
// once when this page loads and the ordering is fixed for the
// session. Retraining after every single click would also make
// "position in the queue" a confusing moving target. Reload the
// page to re-rank with a freshly retrained classifier.
let items = [];
let decisions = {};  // key `${path}:${idx}:${id}` -> bool
let pos = 0, history = [];

const counter = document.getElementById('counter');
const stats = document.getElementById('stats');
const fill = document.getElementById('progress-fill');
const cropImg = document.getElementById('crop');
const doneEl = document.getElementById('done');
const errEl = document.getElementById('err');
const controls = document.getElementById('controls');
const tileNameEl = document.getElementById('tile-name');
const probEl = document.getElementById('prob');

function key(it) { return `${it.path}:${it.idx}:${it.id}`; }

function updateStats() {
  const vals = Object.values(decisions);
  const nTrue = vals.filter(v => v === true).length;
  const nFalse = vals.filter(v => v === false).length;
  stats.textContent = `track: ${nTrue}   junk: ${nFalse}`;
}

function showCurrent() {
  if (pos >= items.length) {
    cropImg.style.display = 'none';
    controls.style.display = 'none';
    doneEl.style.display = 'block';
    counter.textContent = `${items.length} / ${items.length} reviewed`;
    return;
  }
  const it = items[pos];
  const tileLabel = it.path.split('/').pop();
  counter.textContent = `${pos + 1} / ${items.length} (uncertainty-ranked)`;
  tileNameEl.textContent = tileLabel;
  probEl.textContent = it.prob.toFixed(3);
  fill.style.width = `${100 * pos / items.length}%`;
  cropImg.src =
    `/label_segment_crop/${it.path}/${it.idx}/${it.id}?${houghQS}`
    + `&_=${Date.now()}`;
}

async function decide(value) {
  if (pos >= items.length) return;
  const it = items[pos];
  history.push(it);
  decisions[key(it)] = value;
  updateStats();
  pos++;
  showCurrent();
  await fetch(`/label_decide/${it.path}/${it.idx}?${houghQS}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: it.id, decision: value}),
  });
}

function undo() {
  if (history.length === 0) return;
  const it = history.pop();
  delete decisions[key(it)];
  pos = items.findIndex(o => key(o) === key(it));
  updateStats();
  showCurrent();
}

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'ArrowLeft' || ev.key.toLowerCase() === 'f') decide(false);
  else if (ev.key === 'ArrowRight' || ev.key.toLowerCase() === 'j') decide(true);
  else if (ev.key === 'Backspace') undo();
});

async function init() {
  const res = await fetch(`/label_uncertain_segments?${houghQS}`);
  const data = await res.json();
  if (!res.ok) {
    controls.style.display = 'none';
    errEl.style.display = 'block';
    errEl.textContent = data.error || 'failed to load';
    counter.textContent = 'error';
    return;
  }
  items = data.items;
  updateStats();
  showCurrent();
}

init();
</script>
</body>
</html>
"""
