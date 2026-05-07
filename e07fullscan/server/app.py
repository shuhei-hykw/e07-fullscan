from __future__ import annotations

import io
import os
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, abort, render_template_string, send_file

from e07fullscan.io import load_spng

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
    .btn-active { background: #0055ff; border-color: #0077ff; }
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
      <button id="btn-blur" class="btn" onclick="setMode('blur')">GAUSSIAN BLUR</button>
      <button id="btn-bin" class="btn" onclick="setMode('bin')">BINARIZATION</button>
      <button id="btn-raw" class="btn btn-active" onclick="setMode('raw')">ORIGINAL RAW</button>
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
      <div style="font-size: 0.8em; color: #888;">{{ selected_json }} [MODE: <span id="mode-name">RAW</span>]</div>
      <input type="range" id="z-range" min="0" max="{{ max_idx }}" value="0" oninput="update(this.value)">
      <span style="font-size: 0.8em;">IDX: <span id="idx">0</span> / {{ max_idx + 1 }}</span>
    </div>
    <div id="viewport"><img id="target" src="/image/raw/{{ rel_dir_path }}/{{ selected_json }}/0" class="mode-fit" draggable="false"></div>
    <script>
      let currentMode = 'raw';
      const range = document.getElementById('z-range');
      const targetImg = document.getElementById('target');
      const relPath = "{{ rel_dir_path }}/{{ selected_json }}";

      function setMode(mode) {
        currentMode = mode;
        document.querySelectorAll('.btn').forEach(b => b.classList.remove('btn-active'));
        if (mode === 'raw') document.getElementById('btn-raw').classList.add('btn-active');
        if (mode === 'blur') document.getElementById('btn-blur').classList.add('btn-active');
        if (mode === 'bin') document.getElementById('btn-bin').classList.add('btn-active');
        document.getElementById('mode-name').innerText = mode.toUpperCase();
        update(range.value);
      }

      function update(val) {
        val = Math.max(0, Math.min(val, {{ max_idx }}));
        document.getElementById('idx').innerText = val;
        targetImg.src = `/image/${currentMode}/${relPath}/${val}`;
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
    </script>
    {% else %}
    <div id="viewport" style="display:flex; align-items:center; justify-content:center;">SELECT A JSON FILE</div>
    {% endif %}
  </div>
</body>
</html>
"""

_VALID_MODES = {"raw", "blur", "bin"}


def _apply_mode(img: np.ndarray, mode: str) -> np.ndarray:
    if mode == "blur":
        return cv2.GaussianBlur(img, (5, 5), 0)
    if mode == "bin":
        blurred = cv2.GaussianBlur(img, (5, 5), 0)
        return cv2.adaptiveThreshold(
            blurred, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
            11, 2,
        )
    return img


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

    @app.route("/image/<mode>/<path:json_rel_path>/<int:idx>")
    def get_image(mode: str, json_rel_path: str, idx: int):
        if mode not in _VALID_MODES:
            abort(400)
        json_path = _safe_resolve(json_rel_path)
        try:
            reader = load_spng(json_path)
            img = _apply_mode(reader.read(idx), mode)
            _, buf = cv2.imencode(".png", img)
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
