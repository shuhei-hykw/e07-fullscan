from __future__ import annotations

import io
import os
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, abort, render_template_string, request, send_file

from e07fullscan.io import load_spng

Z_PROJ_HALF = 4  # slices on each side for Z-projection (total = 2*Z_PROJ_HALF+1)

_TEMPLATE = """
<html>
<head>
  <title>E07 SPNG Explorer</title>
  <style>
    body { background: #1a1a1a; color: #ddd; font-family: sans-serif; margin: 0; display: flex; height: 100vh; overflow: hidden; }
    #sidebar { width: 300px; background: #252525; border-right: 1px solid #444; display: flex; flex-direction: column; flex-shrink: 0; box-sizing: border-box; }
    .sidebar-section { border-bottom: 1px solid #444; padding: 10px; box-sizing: border-box; }
    .scroll-area { flex: 1; overflow-y: auto; padding: 10px; }
    h3 { font-size: 0.8em; color: #666; text-transform: uppercase; margin: 10px 0 5px 0; }
    .btn {
      background: #444; color: #eee; border: 1px solid #666; padding: 8px; cursor: pointer;
      border-radius: 3px; font-size: 0.8em; width: 100%; margin-bottom: 8px;
      text-align: center; display: block; text-decoration: none; box-sizing: border-box;
    }
    .btn:hover { background: #555; }
    .pipeline { display: flex; flex-direction: column; gap: 6px; }
    .step {
      display: flex; align-items: center; gap: 8px;
      background: #333; border: 1px solid #555; border-radius: 3px; padding: 8px 10px;
      cursor: pointer; user-select: none; font-size: 0.85em;
    }
    .step:hover { background: #3a3a3a; }
    .step.active { border-color: #0077ff; background: #0a2a55; }
    .step input[type=checkbox] { accent-color: #0077ff; width: 15px; height: 15px; cursor: pointer; }
    .step-label { flex: 1; }
    .step-num { color: #666; font-size: 0.8em; min-width: 16px; }
    .list-item { display: block; color: #aaa; text-decoration: none; padding: 4px; font-size: 0.85em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .list-item:hover { background: #333; color: #fff; }
    .list-item.active { background: #0055ff; color: #fff; }
    #main { flex-grow: 1; display: flex; flex-direction: column; background: #000; overflow: hidden; }
    #header { background: #333; padding: 10px; text-align: center; border-bottom: 1px solid #444; z-index: 20; }
    #viewport { flex-grow: 1; overflow: auto; display: block; text-align: center; cursor: grab; }
    img.mode-fit { max-height: 100%; max-width: 100%; object-fit: contain; }
    img.mode-actual { max-height: none; max-width: none; object-fit: none; }
    input[type=range] { width: 60%; vertical-align: middle; }
  </style>
</head>
<body>
  <div id="sidebar">
    <div class="sidebar-section">
      <a href="/view/" class="btn" style="background:#522;">GO TO ROOT</a>
      <button class="btn" onclick="toggleViewMode()">VIEW: FIT/ACTUAL</button>
    </div>
    <div class="sidebar-section">
      <h3>Processing Pipeline</h3>
      <div class="pipeline">
        <label class="step" id="step-zpj">
          <span class="step-num">1</span>
          <input type="checkbox" id="cb-zpj" onchange="updateStep('step-zpj','cb-zpj'); updateImage()">
          <span class="step-label">Z-Projection</span>
        </label>
        <label class="step" id="step-fog">
          <span class="step-num">2</span>
          <input type="checkbox" id="cb-fog" onchange="updateStep('step-fog','cb-fog'); updateImage()">
          <span class="step-label">Fog Removal</span>
        </label>
        <label class="step" id="step-thr">
          <span class="step-num">3</span>
          <input type="checkbox" id="cb-thr" onchange="updateStep('step-thr','cb-thr'); updateImage()">
          <span class="step-label">Threshold (Otsu)</span>
        </label>
        <label class="step" id="step-den">
          <span class="step-num">4</span>
          <input type="checkbox" id="cb-den" onchange="updateStep('step-den','cb-den'); updateImage()">
          <span class="step-label">Noise Removal</span>
        </label>
        <label class="step" id="step-hough">
          <span class="step-num">5</span>
          <input type="checkbox" id="cb-hough" onchange="updateStep('step-hough','cb-hough'); updateImage()">
          <span class="step-label">Hough Lines</span>
        </label>
      </div>
    </div>
    <div class="scroll-area">
      <h3>PATH: /{{ rel_dir_path }}</h3>
      <a href="/view/{{ parent_path }}" class="list-item">.. (UP)</a>
      {% for d in dirs %}<a href="/view/{{ rel_dir_path }}/{{ d }}" class="list-item">DIR: {{ d }}/</a>{% endfor %}
      <h3>JSON FILES</h3>
      {% for j in jsons %}<a href="/view/{{ rel_dir_path }}/{{ j }}" class="list-item {{ 'active' if j == selected_json else '' }}">JSON: {{ j }}</a>{% endfor %}
    </div>
  </div>
  <div id="main">
    {% if selected_json %}
    <div id="header">
      <div style="font-size: 0.8em; color: #888;">{{ selected_json }}</div>
      <input type="range" id="z-range" min="0" max="{{ max_idx }}" value="0" oninput="update(this.value)">
      <span style="font-size: 0.8em;">IDX: <span id="idx">0</span> / {{ max_idx + 1 }}</span>
    </div>
    <div id="viewport"><img id="target" class="mode-fit" draggable="false"></div>
    <script>
      const relPath = "{{ rel_dir_path }}/{{ selected_json }}";
      const range = document.getElementById('z-range');
      const targetImg = document.getElementById('target');

      function flag(id) { return document.getElementById(id).checked ? 1 : 0; }

      function buildUrl(idx) {
        return `/image/${relPath}/${idx}` +
          `?zpj=${flag('cb-zpj')}&fog=${flag('cb-fog')}` +
          `&thr=${flag('cb-thr')}&den=${flag('cb-den')}` +
          `&hough=${flag('cb-hough')}`;
      }

      function update(val) {
        val = Math.max(0, Math.min(val, {{ max_idx }}));
        document.getElementById('idx').innerText = val;
        targetImg.src = buildUrl(val);
      }

      function updateImage() { update(parseInt(range.value)); }

      function updateStep(stepId, cbId) {
        document.getElementById(stepId).classList.toggle('active',
          document.getElementById(cbId).checked);
      }

      function toggleViewMode() {
        targetImg.classList.toggle('mode-fit');
        targetImg.classList.toggle('mode-actual');
      }

      window.addEventListener('wheel', (e) => {
        if (e.target.closest('#sidebar')) return;
        e.preventDefault();
        range.value = parseInt(range.value) + (e.deltaY > 0 ? 1 : -1);
        update(range.value);
      }, { passive: false });

      window.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowRight') { range.value = parseInt(range.value) + 1; update(range.value); }
        if (e.key === 'ArrowLeft')  { range.value = parseInt(range.value) - 1; update(range.value); }
      });

      update(0);
    </script>
    {% else %}
    <div id="viewport" style="display:flex; align-items:center; justify-content:center;">SELECT A JSON FILE</div>
    {% endif %}
  </div>
</body>
</html>
"""


def _process(
    img: np.ndarray,
    fog: bool,
    thr: bool,
    den: bool,
    hough: bool,
) -> np.ndarray:
    """Apply the selected pipeline steps in order."""
    current = img  # uint8 grayscale H×W

    if fog:
        blurred = cv2.GaussianBlur(current, (31, 31), 0)
        current = cv2.subtract(blurred, current)

    if thr:
        _, current = cv2.threshold(
            current, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )

    if den:
        contours, _ = cv2.findContours(current, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        noise = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 5:
                noise.append(cnt)
                continue
            perimeter = cv2.arcLength(cnt, True)
            if perimeter > 0 and area < 30 and (perimeter ** 2) / area < 15:
                noise.append(cnt)
        cv2.drawContours(current, noise, -1, 0, thickness=-1)

    if hough:
        lines = cv2.HoughLinesP(
            current, 1, np.pi / 180,
            threshold=20, minLineLength=15, maxLineGap=8,
        )
        output = cv2.cvtColor(current, cv2.COLOR_GRAY2BGR)
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                cv2.line(output, (x1, y1), (x2, y2), (0, 255, 0), 1)
        return output

    return current


def create_app(root_dir: Path | str) -> Flask:
    """
    Create the Flask viewer app rooted at *root_dir*.

    Parameters
    ----------
    root_dir:
        Root directory that the browser is allowed to navigate.
    """
    root = Path(root_dir).resolve()
    app = Flask(__name__)

    def _safe_resolve(subpath: str) -> Path:
        full = (root / subpath).resolve()
        if not str(full).startswith(str(root)):
            abort(403)
        return full

    @app.route("/")
    @app.route("/view/")
    @app.route("/view/<path:subpath>")
    def viewer(subpath: str = "") -> str:
        full_path = _safe_resolve(subpath)

        if full_path.is_dir():
            current_dir = full_path
            selected_json = None
            rel_dir_path = subpath
        else:
            current_dir = full_path.parent
            selected_json = full_path.name
            rel_dir_path = os.path.dirname(subpath)

        items = sorted(os.listdir(current_dir))
        dirs = [i for i in items if (current_dir / i).is_dir()]
        jsons = [i for i in items if i.endswith(".json")]

        max_idx = 0
        if selected_json:
            try:
                max_idx = len(load_spng(current_dir / selected_json)) - 1
            except Exception:
                pass

        return render_template_string(
            _TEMPLATE,
            rel_dir_path=rel_dir_path,
            dirs=dirs,
            jsons=jsons,
            selected_json=selected_json,
            max_idx=max_idx,
            parent_path=os.path.dirname(rel_dir_path.rstrip("/")),
        )

    @app.route("/image/<path:json_rel_path>/<int:idx>")
    def get_image(json_rel_path: str, idx: int):
        json_path = _safe_resolve(json_rel_path)
        zpj   = request.args.get("zpj",   "0") == "1"
        fog   = request.args.get("fog",   "0") == "1"
        thr   = request.args.get("thr",   "0") == "1"
        den   = request.args.get("den",   "0") == "1"
        hough = request.args.get("hough", "0") == "1"
        try:
            reader = load_spng(json_path)
            if zpj:
                lo = max(0, idx - Z_PROJ_HALF)
                hi = min(len(reader) - 1, idx + Z_PROJ_HALF)
                slices = [reader.read(i) for i in range(lo, hi + 1)]
                img = np.mean(slices, axis=0).astype(np.uint8)
            else:
                img = reader.read(idx)
            result = _process(img, fog=fog, thr=thr, den=den, hough=hough)
            _, buf = cv2.imencode(".png", result)
            return send_file(io.BytesIO(buf.tobytes()), mimetype="image/png")
        except Exception as e:
            return str(e), 500

    return app


def run(
    root_dir: Path | str,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Start the viewer server."""
    create_app(root_dir).run(host=host, port=port, debug=False, threaded=True)
