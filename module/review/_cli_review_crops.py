"""Vertex crop review/labelling server.

Usage:
  python scripts/review_crops.py [--crops DIR] [--labels FILE] [--port N]

Default crops dir : results/vertex_crops_v6/
Default labels CSV: results/vertex_crops_v6_labels.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import time
from pathlib import Path

from flask import (
  Flask, jsonify, redirect, render_template_string,
  request, send_file,
)

# --- category definitions (label, keyboard key, CSS colour) ---
CATEGORIES = [
  ("good",    "1", "#4a4"),  # clear vertex candidate
  ("bad",     "2", "#c44"),  # background / fake
  ("unclear", "3", "#888"),  # uncertain, revisit later
]

_TMPL = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Vertex Crop Review</title>
<style>
* { box-sizing: border-box; }
body { background:#1a1a1a; color:#ddd; font-family:sans-serif;
     margin:0; display:flex; height:100vh; overflow:hidden; }
#sidebar { width:230px; background:#252525;
       border-right:1px solid #444;
       display:flex; flex-direction:column;
       flex-shrink:0; padding:10px; gap:8px; overflow-y:auto; }
h3 { font-size:0.75em; color:#666; text-transform:uppercase;
   margin:6px 0 3px 0; }
.info { font-size:0.78em; color:#aaa; word-break:break-all; }
.mono { font-family:monospace; }
.cat-btn {
  width:100%; padding:10px 8px; cursor:pointer;
  border:1px solid #555; border-radius:4px;
  font-size:0.9em; text-align:left; display:flex;
  align-items:center; gap:8px; transition:opacity .1s;
}
.cat-btn:hover { filter:brightness(1.3); }
.cat-btn .key { font-family:monospace; font-size:0.8em;
        background:#333; border:1px solid #555;
        border-radius:3px; padding:1px 5px;
        color:#aaa; flex-shrink:0; }
.nav-row { display:flex; gap:6px; }
.nav-btn { flex:1; padding:7px; background:#333; color:#eee;
       border:1px solid #555; border-radius:3px;
       cursor:pointer; font-size:0.85em; }
.nav-btn:hover { background:#444; }
.prog-bar { width:100%; height:8px; background:#333;
       border-radius:4px; overflow:hidden; }
.prog-fill { height:100%; background:#0077ff;
       border-radius:4px; transition:width .3s; }
.stat-row { display:flex; justify-content:space-between;
       font-size:0.78em; color:#888; }
.labeled  { color:#4f4; }
.unlabeled { color:#888; }
#jump-input { width:60px; background:#333; color:#ddd;
        border:1px solid #555; padding:4px;
        font-size:0.85em; border-radius:3px; }
.jump-row { display:flex; gap:6px; align-items:center; }
.jump-go { padding:4px 10px; background:#444; color:#eee;
      border:1px solid #555; border-radius:3px;
      cursor:pointer; font-size:0.85em; }
#main { flex-grow:1; display:flex; flex-direction:column;
    background:#000; overflow:hidden; }
#crop-area { flex-grow:1; display:flex;
       align-items:center; justify-content:center;
       overflow:hidden; position:relative; }
#crop-img  { max-width:100%; max-height:100%;
       object-fit:contain; transition:opacity .1s; }
#label-badge {
  position:absolute; top:10px; right:14px;
  font-size:1em; font-weight:bold; padding:4px 12px;
  border-radius:20px; border:2px solid #555;
  background:#1a1a1a; color:#fff; display:none;
}
#crop-title { background:#222; padding:6px 12px;
        font-size:0.8em; color:#888; border-top:1px solid #333;
        text-align:center; flex-shrink:0; font-family:monospace; }
</style>
</head>
<body>
<div id="sidebar">
  <div>
    <h3>Progress</h3>
    <div class="prog-bar">
      <div class="prog-fill" id="prog-fill"
         style="width:{{ pct }}%;"></div>
    </div>
    <div class="stat-row" style="margin-top:4px;">
      <span class="labeled" id="n-labeled">{{ n_labeled }}</span>
      <span style="color:#555;"> / {{ n_total }}</span>
      <span style="color:#555;">{{ "%.0f"|format(pct) }}%</span>
    </div>
    <div class="stat-row" style="margin-top:3px;" id="cat-summary">
      {% for cat,key,col in categories %}
      <span style="color:{{ col }};" id="cnt-{{ cat }}">
        {{ counts.get(cat, 0) }}{{ cat[:3] }}
      </span>
      {% endfor %}
    </div>
  </div>

  <div>
    <h3>Categorize  <span style="color:#555;">(auto-advance)</span></h3>
    {% for cat,key,col in categories %}
    <button class="cat-btn"
        style="background:{{ col }}22; border-color:{{ col }}88; color:{{ col }};"
        id="btn-{{ cat }}"
        onclick="setLabel('{{ cat }}')">
      <span class="key">{{ key }}</span> {{ cat }}
    </button>
    {% endfor %}
  </div>

  <div>
    <h3>Navigate</h3>
    <div class="nav-row">
      <button class="nav-btn" onclick="go(cur-1)">&#9664; Prev</button>
      <button class="nav-btn" onclick="go(cur+1)">Next &#9654;</button>
    </div>
    <div class="jump-row" style="margin-top:6px;">
      <input id="jump-input" type="number" min="0"
           max="{{ n_total - 1 }}" placeholder="#">
      <button class="jump-go" onclick="jump()">Go</button>
    </div>
    <div class="stat-row" style="margin-top:6px;">
      <span id="cur-idx">{{ start_idx }}</span>
      <span style="color:#555;"> / {{ n_total }}</span>
    </div>
  </div>

  <div>
    <h3>Unlabeled</h3>
    <button class="nav-btn" onclick="goNextUnlabeled()"
        style="width:100%;">Next Unlabeled &#9654;</button>
  </div>
</div>

<div id="main">
  <div id="crop-area">
    <img id="crop-img" src="" alt="crop">
    <div id="label-badge"></div>
  </div>
  <div id="crop-title" id="crop-title">—</div>
</div>

<script>
const CATEGORIES = {{ cat_json|safe }};
const NAMES      = {{ names_json|safe }};
const LABELS     = {{ labels_json|safe }};  // {filename: label}
const N          = NAMES.length;
let cur          = {{ start_idx }};

function updateBadge(label) {
  const badge = document.getElementById('label-badge');
  if (!label) { badge.style.display='none'; return; }
  const cat = CATEGORIES.find(c => c[0] === label);
  badge.textContent   = label;
  badge.style.display = 'block';
  badge.style.color   = cat ? cat[2] : '#fff';
  badge.style.borderColor = cat ? cat[2] : '#555';
}

function load(idx) {
  if (idx < 0 || idx >= N) return;
  cur = idx;
  document.getElementById('cur-idx').textContent = idx;
  const name = NAMES[idx];
  const img  = document.getElementById('crop-img');
  img.style.opacity = '0.4';
  img.onload = () => { img.style.opacity = '1'; };
  img.src    = '/crop/' + encodeURIComponent(name);
  document.getElementById('crop-title').textContent = name;
  updateBadge(LABELS[name] || null);
}

function go(idx) {
  idx = Math.max(0, Math.min(idx, N-1));
  load(idx);
}

function jump() {
  const v = parseInt(document.getElementById('jump-input').value);
  if (!isNaN(v)) go(v);
}

function goNextUnlabeled() {
  for (let i = cur+1; i < N; i++) {
    if (!LABELS[NAMES[i]]) { go(i); return; }
  }
  for (let i = 0; i < cur; i++) {
    if (!LABELS[NAMES[i]]) { go(i); return; }
  }
}

function setLabel(cat) {
  const name = NAMES[cur];
  fetch('/label', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({name, label: cat})
  }).then(r => r.json()).then(d => {
    LABELS[name] = cat;
    updateBadge(cat);
    // update progress
    document.getElementById('prog-fill').style.width = d.pct + '%';
    document.getElementById('n-labeled').textContent = d.n_labeled;
    // update per-cat counts
    for (const [c,,] of CATEGORIES) {
      const el = document.getElementById('cnt-' + c);
      if (el) el.textContent = (d.counts[c] || 0) + c.slice(0,3);
    }
    // auto-advance to next unlabeled
    let next = cur + 1;
    while (next < N && LABELS[NAMES[next]]) next++;
    if (next < N) go(next); else go(cur+1);
  });
}

window.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT') return;
  for (const [cat, key,] of CATEGORIES) {
    if (e.key === key) { setLabel(cat); return; }
  }
  if (e.key === 'ArrowRight') go(cur+1);
  if (e.key === 'ArrowLeft')  go(cur-1);
});

load(cur);
</script>
</body>
</html>
"""


def _parse_filename(name: str) -> dict:
  """Extract metadata encoded in the crop filename."""
  m = re.search(
    r'n(\d+)_sl(\d+)_z(\d+)_x(\d+)_y(\d+)', name
  )
  if not m:
    return {}
  return {
    "n_tracks": int(m.group(1)),
    "n_slices": int(m.group(2)),
    "z": int(m.group(3)),
    "x": int(m.group(4)),
    "y": int(m.group(5)),
  }


def create_app(crops_dir: Path, labels_path: Path) -> Flask:
  app = Flask(__name__)

  names: list[str] = sorted(
    p.name for p in crops_dir.glob("*.png")
  )
  labels: dict[str, str] = {}

  if labels_path.exists():
    with labels_path.open(newline="") as f:
      for row in csv.DictReader(f):
        labels[row["filename"]] = row["label"]

  def _save() -> None:
    with labels_path.open("w", newline="") as f:
      w = csv.DictWriter(
        f, fieldnames=["filename", "label", "ts"]
      )
      w.writeheader()
      for name, label in labels.items():
        w.writerow({
          "filename": name,
          "label": label,
          "ts": labels.get("__ts__" + name, ""),
        })

  def _stats() -> dict:
    counts: dict[str, int] = {}
    for label in labels.values():
      counts[label] = counts.get(label, 0) + 1
    n_labeled = len(labels)
    n_total   = len(names)
    pct = 100.0 * n_labeled / n_total if n_total else 0.0
    return {
      "n_labeled": n_labeled,
      "n_total":   n_total,
      "pct":       round(pct, 1),
      "counts":    counts,
    }

  def _start_idx() -> int:
    for i, name in enumerate(names):
      if name not in labels:
        return i
    return 0

  @app.route("/")
  def index():
    return redirect("/review/")

  @app.route("/review/")
  def review():
    import json
    st = _stats()
    return render_template_string(
      _TMPL,
      categories=CATEGORIES,
      cat_json=json.dumps(CATEGORIES),
      names_json=json.dumps(names),
      labels_json=json.dumps(labels),
      n_total=len(names),
      n_labeled=st["n_labeled"],
      pct=st["pct"],
      counts=st["counts"],
      start_idx=_start_idx(),
    )

  @app.route("/crop/<path:name>")
  def serve_crop(name: str):
    p = crops_dir / name
    if not p.exists() or not p.is_file():
      return "not found", 404
    return send_file(io.BytesIO(p.read_bytes()),
             mimetype="image/png")

  @app.route("/label", methods=["POST"])
  def set_label():
    data  = request.get_json(force=True)
    name  = data.get("name", "")
    label = data.get("label", "")
    if name and label and name in set(names):
      labels[name] = label
      _save()
    st = _stats()
    return jsonify(st)

  return app


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Vertex crop review server"
  )
  parser.add_argument(
    "--crops",
    default="results/vertex_crops_v6",
    help="Directory of PNG crops",
  )
  parser.add_argument(
    "--labels",
    default="results/vertex_crops_v6_labels.csv",
    help="Output CSV for labels",
  )
  parser.add_argument("--port", type=int, default=8010)
  parser.add_argument("--host", default="0.0.0.0")
  args = parser.parse_args()

  crops_dir   = Path(args.crops).resolve()
  labels_path = Path(args.labels).resolve()

  if not crops_dir.exists():
    raise SystemExit(f"crops dir not found: {crops_dir}")

  n = len(list(crops_dir.glob("*.png")))
  print(f"Loaded {n} crops from {crops_dir}")
  if labels_path.exists():
    with labels_path.open() as f:
      n_lab = sum(1 for _ in f) - 1
    print(f"Resuming {n_lab} existing labels from {labels_path}")
  print(f"Open: http://localhost:{args.port}/review/")

  create_app(crops_dir, labels_path).run(
    host=args.host, port=args.port,
    debug=False, threaded=True,
  )


if __name__ == "__main__":
  main()
