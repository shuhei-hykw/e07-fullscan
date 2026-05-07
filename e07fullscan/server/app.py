from __future__ import annotations

import io
import os
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Flask, abort, render_template_string, request, send_file

from e07fullscan.io import load_spng

# --- Default pipeline parameters ---
Z_PROJ_HALF    = 4
FOG_KSIZE      = 31
NOISE_AREA_MIN = 5
NOISE_AREA_MAX = 30
NOISE_COMPACT  = 15
HOUGH_THRESH   = 20
HOUGH_MIN_LINE = 15
HOUGH_MAX_GAP  = 8

_TEMPLATE = """
<html>
<head>
  <title>E07 SPNG Explorer</title>
  <style>
    body { background:#1a1a1a; color:#ddd; font-family:sans-serif;
           margin:0; display:flex; height:100vh; overflow:hidden; }
    #sidebar { width:300px; background:#252525;
               border-right:1px solid #444; display:flex;
               flex-direction:column; flex-shrink:0; box-sizing:border-box; }
    .sidebar-section { border-bottom:1px solid #444; padding:10px;
                       box-sizing:border-box; }
    .scroll-area { flex:1; overflow-y:auto; padding:10px; }
    h3 { font-size:0.8em; color:#666; text-transform:uppercase;
         margin:10px 0 5px 0; }
    .btn { background:#444; color:#eee; border:1px solid #666; padding:8px;
           cursor:pointer; border-radius:3px; font-size:0.8em; width:100%;
           margin-bottom:8px; text-align:center; display:block;
           text-decoration:none; box-sizing:border-box; }
    .btn:hover  { background:#555; }
    .btn.active { background:#0a2a55; border-color:#0077ff; }
    .pipeline { display:flex; flex-direction:column; gap:6px; }
    .step { display:flex; align-items:center; gap:8px; background:#333;
            border:1px solid #555; border-radius:3px; padding:8px 10px;
            cursor:pointer; user-select:none; font-size:0.85em; }
    .step:hover  { background:#3a3a3a; }
    .step.active { border-color:#0077ff; background:#0a2a55; }
    .step input[type=checkbox] { accent-color:#0077ff;
                                  width:15px; height:15px; cursor:pointer; }
    .step-label { flex:1; }
    .step-num   { color:#666; font-size:0.8em; min-width:16px; }
    .list-item  { display:block; color:#aaa; text-decoration:none; padding:4px;
                  font-size:0.85em; white-space:nowrap; overflow:hidden;
                  text-overflow:ellipsis; }
    .list-item:hover  { background:#333; color:#fff; }
    .list-item.active { background:#0055ff; color:#fff; }
    #main { flex-grow:1; display:flex; flex-direction:column;
            background:#000; overflow:hidden; }
    #header { background:#333; padding:10px; text-align:center;
              border-bottom:1px solid #444; z-index:20; }
    #viewport { flex-grow:1; overflow:auto; display:block;
                text-align:center; cursor:grab; }
    img.mode-fit    { max-height:100%; max-width:100%; object-fit:contain; }
    img.mode-actual { max-height:none; max-width:none; object-fit:none; }
    input[type=range] { width:60%; vertical-align:middle; }
    #stats-panel { height:360px; border-top:1px solid #444; display:none;
                   overflow:auto; background:#111; text-align:center;
                   flex-shrink:0; }
    #stats-panel.visible { display:block; }
    #stats-panel img { height:100%; object-fit:contain; }
    /* parameter sliders */
    .param-row { display:grid; grid-template-columns:90px 1fr 32px;
                 align-items:center; gap:4px; margin-bottom:5px; }
    .param-row label { font-size:0.72em; color:#999; text-align:right; }
    .param-row input[type=range] { width:100%; accent-color:#0077ff; }
    .param-row span { font-size:0.72em; color:#ddd;
                      font-family:monospace; text-align:right; }
    .param-group { margin-bottom:8px; }
    .param-group-label { font-size:0.7em; color:#555;
                         text-transform:uppercase; margin-bottom:3px; }
  </style>
</head>
<body>
<div id="sidebar">
  <div class="sidebar-section">
    <a href="/view/" class="btn" style="background:#522;">GO TO ROOT</a>
    <button class="btn" onclick="toggleViewMode()">VIEW: FIT/ACTUAL</button>
    <button class="btn" id="btn-stats" onclick="toggleStats()">STATS</button>
  </div>

  <div class="sidebar-section">
    <h3>Processing Pipeline</h3>
    <div class="pipeline">
      <label class="step" id="step-zpj">
        <span class="step-num">1</span>
        <input type="checkbox" id="cb-zpj"
               onchange="updateStep('step-zpj','cb-zpj'); updateAll()">
        <span class="step-label">Z-Projection</span>
      </label>
      <label class="step" id="step-fog">
        <span class="step-num">2</span>
        <input type="checkbox" id="cb-fog"
               onchange="updateStep('step-fog','cb-fog'); updateAll()">
        <span class="step-label">Fog Removal</span>
      </label>
      <label class="step" id="step-thr">
        <span class="step-num">3</span>
        <input type="checkbox" id="cb-thr"
               onchange="updateStep('step-thr','cb-thr'); updateAll()">
        <span class="step-label">Threshold (Otsu)</span>
      </label>
      <label class="step" id="step-den">
        <span class="step-num">4</span>
        <input type="checkbox" id="cb-den"
               onchange="updateStep('step-den','cb-den'); updateAll()">
        <span class="step-label">Noise Removal</span>
      </label>
      <label class="step" id="step-hough">
        <span class="step-num">5</span>
        <input type="checkbox" id="cb-hough"
               onchange="updateStep('step-hough','cb-hough'); updateAll()">
        <span class="step-label">Hough Lines</span>
      </label>
      <label class="step" id="step-trk">
        <span class="step-num">6</span>
        <input type="checkbox" id="cb-trk"
               onchange="updateStep('step-trk','cb-trk'); updateAll()">
        <span class="step-label">Tracks Only</span>
      </label>
    </div>
  </div>

  <div class="sidebar-section">
    <h3>Parameters</h3>
    <div class="param-group">
      <div class="param-group-label">Z-Projection</div>
      <div class="param-row">
        <label>half slices</label>
        <input type="range" id="zpj_half" min="1" max="10" step="1"
               value="{{ zpj_half }}" oninput="sv('zpj_half'); updateAll()">
        <span id="zpj_half_v">{{ zpj_half }}</span>
      </div>
    </div>
    <div class="param-group">
      <div class="param-group-label">Fog Removal</div>
      <div class="param-row">
        <label>ksize</label>
        <input type="range" id="fog_k" min="3" max="101" step="2"
               value="{{ fog_k }}" oninput="sv('fog_k'); updateAll()">
        <span id="fog_k_v">{{ fog_k }}</span>
      </div>
    </div>
    <div class="param-group">
      <div class="param-group-label">Noise Removal</div>
      <div class="param-row">
        <label>area min</label>
        <input type="range" id="noise_amin" min="1" max="30" step="1"
               value="{{ noise_amin }}"
               oninput="sv('noise_amin'); updateAll()">
        <span id="noise_amin_v">{{ noise_amin }}</span>
      </div>
      <div class="param-row">
        <label>area max</label>
        <input type="range" id="noise_amax" min="5" max="200" step="5"
               value="{{ noise_amax }}"
               oninput="sv('noise_amax'); updateAll()">
        <span id="noise_amax_v">{{ noise_amax }}</span>
      </div>
      <div class="param-row">
        <label>compact</label>
        <input type="range" id="noise_cmp" min="5" max="50" step="1"
               value="{{ noise_cmp }}"
               oninput="sv('noise_cmp'); updateAll()">
        <span id="noise_cmp_v">{{ noise_cmp }}</span>
      </div>
    </div>
    <div class="param-group">
      <div class="param-group-label">Hough Lines</div>
      <div class="param-row">
        <label>threshold</label>
        <input type="range" id="hough_thr" min="5" max="80" step="1"
               value="{{ hough_thr }}"
               oninput="sv('hough_thr'); updateAll()">
        <span id="hough_thr_v">{{ hough_thr }}</span>
      </div>
      <div class="param-row">
        <label>min length</label>
        <input type="range" id="hough_ml" min="3" max="100" step="1"
               value="{{ hough_ml }}"
               oninput="sv('hough_ml'); updateAll()">
        <span id="hough_ml_v">{{ hough_ml }}</span>
      </div>
      <div class="param-row">
        <label>max gap</label>
        <input type="range" id="hough_mg" min="1" max="50" step="1"
               value="{{ hough_mg }}"
               oninput="sv('hough_mg'); updateAll()">
        <span id="hough_mg_v">{{ hough_mg }}</span>
      </div>
    </div>
  </div>

  <div class="scroll-area">
    <h3>PATH: /{{ rel_dir_path }}</h3>
    <a href="/view/{{ parent_path }}" class="list-item">.. (UP)</a>
    {% for d in dirs %}
    <a href="/view/{{ rel_dir_path }}/{{ d }}" class="list-item">
      DIR: {{ d }}/</a>
    {% endfor %}
    <h3>JSON FILES</h3>
    {% for j in jsons %}
    <a href="/view/{{ rel_dir_path }}/{{ j }}"
       class="list-item {{ 'active' if j == selected_json else '' }}">
      JSON: {{ j }}</a>
    {% endfor %}
  </div>
</div>

<div id="main">
  {% if selected_json %}
  <div id="header">
    <div style="font-size:0.8em; color:#888;">{{ selected_json }}</div>
    <input type="range" id="z-range" min="0" max="{{ max_idx }}"
           value="0" oninput="update(this.value)">
    <span style="font-size:0.8em;">
      IDX: <span id="idx">0</span> / {{ max_idx + 1 }}
    </span>
  </div>
  <div id="viewport"><img id="target" class="mode-fit" draggable="false"></div>
  <div id="stats-panel"><img id="stats-img" draggable="false"></div>
  <script>
    const relPath    = "{{ rel_dir_path }}/{{ selected_json }}";
    const range      = document.getElementById('z-range');
    const targetImg  = document.getElementById('target');
    const statsImg   = document.getElementById('stats-img');
    const statsPanel = document.getElementById('stats-panel');

    function flag(id) {
      return document.getElementById(id).checked ? 1 : 0;
    }
    function val(id) {
      return document.getElementById(id).value;
    }
    function sv(id) {  // sync slider → displayed value
      document.getElementById(id + '_v').textContent = val(id);
    }

    function flagQuery() {
      return `zpj=${flag('cb-zpj')}&fog=${flag('cb-fog')}` +
             `&thr=${flag('cb-thr')}&den=${flag('cb-den')}` +
             `&hough=${flag('cb-hough')}&trk=${flag('cb-trk')}`;
    }
    function paramQuery() {
      return `zpj_half=${val('zpj_half')}&fog_k=${val('fog_k')}` +
             `&noise_amin=${val('noise_amin')}` +
             `&noise_amax=${val('noise_amax')}` +
             `&noise_cmp=${val('noise_cmp')}` +
             `&hough_thr=${val('hough_thr')}` +
             `&hough_ml=${val('hough_ml')}&hough_mg=${val('hough_mg')}`;
    }
    function fullQuery()     { return flagQuery() + '&' + paramQuery(); }
    function buildUrl(i)     { return `/image/${relPath}/${i}?${fullQuery()}`; }
    function buildStatsUrl(i){ return `/stats/${relPath}/${i}?${fullQuery()}`; }

    function update(v) {
      v = Math.max(0, Math.min(v, {{ max_idx }}));
      document.getElementById('idx').textContent = v;
      targetImg.src = buildUrl(v);
      if (statsPanel.classList.contains('visible'))
        statsImg.src = buildStatsUrl(v);
    }
    function updateAll()  { update(parseInt(range.value)); }
    function updateStep(stepId, cbId) {
      document.getElementById(stepId).classList.toggle('active',
        document.getElementById(cbId).checked);
    }
    function toggleViewMode() {
      targetImg.classList.toggle('mode-fit');
      targetImg.classList.toggle('mode-actual');
    }
    function toggleStats() {
      const visible = statsPanel.classList.toggle('visible');
      document.getElementById('btn-stats').classList.toggle('active', visible);
      if (visible) statsImg.src = buildStatsUrl(parseInt(range.value));
    }

    window.addEventListener('wheel', (e) => {
      if (e.target.closest('#sidebar')) return;
      e.preventDefault();
      range.value = parseInt(range.value) + (e.deltaY > 0 ? 1 : -1);
      update(range.value);
    }, { passive: false });
    window.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight') {
        range.value = parseInt(range.value) + 1; update(range.value);
      }
      if (e.key === 'ArrowLeft') {
        range.value = parseInt(range.value) - 1; update(range.value);
      }
    });

    update(0);
  </script>
  {% else %}
  <div id="viewport"
       style="display:flex; align-items:center; justify-content:center;">
    SELECT A JSON FILE
  </div>
  {% endif %}
</div>
</body>
</html>
"""


def _process(
    img: np.ndarray,
    fog: bool, thr: bool, den: bool, hough: bool, trk: bool,
    fog_k: int      = FOG_KSIZE,
    noise_amin: int = NOISE_AREA_MIN,
    noise_amax: int = NOISE_AREA_MAX,
    noise_cmp: int  = NOISE_COMPACT,
    hough_thr: int  = HOUGH_THRESH,
    hough_ml: int   = HOUGH_MIN_LINE,
    hough_mg: int   = HOUGH_MAX_GAP,
) -> np.ndarray:
    """Apply the selected pipeline steps in order."""
    current = img

    if fog:
        k = fog_k if fog_k % 2 == 1 else fog_k + 1
        blurred = cv2.GaussianBlur(current, (k, k), 0)
        current = cv2.subtract(blurred, current)

    if thr:
        _, current = cv2.threshold(
            current, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )

    if den:
        contours, _ = cv2.findContours(
            current, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        noise = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < noise_amin:
                noise.append(cnt)
                continue
            perimeter = cv2.arcLength(cnt, True)
            if (perimeter > 0 and area < noise_amax
                    and (perimeter ** 2) / area < noise_cmp):
                noise.append(cnt)
        cv2.drawContours(current, noise, -1, 0, thickness=-1)

    if hough or trk:
        lines = cv2.HoughLinesP(
            current, 1, np.pi / 180,
            threshold=hough_thr,
            minLineLength=hough_ml,
            maxLineGap=hough_mg,
        )
        output = (
            np.zeros((*current.shape, 3), dtype=np.uint8)
            if trk else cv2.cvtColor(current, cv2.COLOR_GRAY2BGR)
        )
        if lines is not None:
            for x1, y1, x2, y2 in lines[:, 0]:
                cv2.line(output, (x1, y1), (x2, y2), (0, 255, 0), 1)
        return output

    return current


def _collect_stats(
    img: np.ndarray,
    fog: bool, thr: bool, den: bool, hough_or_trk: bool,
    fog_k: int      = FOG_KSIZE,
    noise_amin: int = NOISE_AREA_MIN,
    noise_amax: int = NOISE_AREA_MAX,
    noise_cmp: int  = NOISE_COMPACT,
    hough_thr: int  = HOUGH_THRESH,
    hough_ml: int   = HOUGH_MIN_LINE,
    hough_mg: int   = HOUGH_MAX_GAP,
) -> dict:
    """Run the pipeline and collect statistics at each stage."""
    stats: dict = {}
    current = img.copy()
    stats["raw_hist"] = np.bincount(current.ravel(), minlength=256)

    if fog:
        k = fog_k if fog_k % 2 == 1 else fog_k + 1
        blurred = cv2.GaussianBlur(current, (k, k), 0)
        current = cv2.subtract(blurred, current)
        stats["fog_hist"] = np.bincount(current.ravel(), minlength=256)

    if thr:
        otsu_val, current = cv2.threshold(
            current, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )
        stats["otsu_val"] = float(otsu_val)

    if thr or den:
        cnts, _ = cv2.findContours(
            current, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        stats["blob_areas_before"] = [cv2.contourArea(c) for c in cnts]

    if den:
        noise = []
        for cnt in cnts:
            area = cv2.contourArea(cnt)
            if area < noise_amin:
                noise.append(cnt)
                continue
            perimeter = cv2.arcLength(cnt, True)
            if (perimeter > 0 and area < noise_amax
                    and (perimeter ** 2) / area < noise_cmp):
                noise.append(cnt)
        cv2.drawContours(current, noise, -1, 0, thickness=-1)
        cnts_after, _ = cv2.findContours(
            current, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        stats["blob_areas_after"] = [cv2.contourArea(c) for c in cnts_after]

    if hough_or_trk:
        lines = cv2.HoughLinesP(
            current, 1, np.pi / 180,
            threshold=hough_thr,
            minLineLength=hough_ml,
            maxLineGap=hough_mg,
        )
        if lines is not None:
            lengths, angles = [], []
            for x1, y1, x2, y2 in lines[:, 0]:
                lengths.append(float(np.hypot(x2 - x1, y2 - y1)))
                angles.append(
                    float(np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180)
                )
            stats["track_lengths"] = lengths
            stats["track_angles"]  = angles
            stats["n_tracks"]      = len(lines)

    return stats


def _ax_style(ax) -> None:
    ax.set_facecolor("#111111")
    ax.tick_params(colors="#888888", labelsize=7)
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.xaxis.label.set_color("#aaaaaa")
    ax.yaxis.label.set_color("#aaaaaa")
    ax.title.set_color("#cccccc")
    ax.title.set_fontsize(9)


def _stats_figure(
    stats: dict,
    flags: dict,
    params: dict,
    idx: int,
    n_slices: int,
) -> plt.Figure:
    """Build a 2×2 matplotlib figure summarising pipeline statistics."""
    fig, axes = plt.subplots(
        2, 2, figsize=(12, 6.5), facecolor="#1a1a1a",
        gridspec_kw={"hspace": 0.45, "wspace": 0.32},
    )
    axes = axes.ravel()
    for ax in axes:
        _ax_style(ax)

    parts = [f"slice {idx}/{n_slices}"]
    if flags["zpj"]:
        h = params["zpj_half"]
        parts.append(f"Z-proj ±{h} ({2*h+1} slices)")
    if flags["fog"]:
        parts.append(f"fog ksize={params['fog_k']}")
    if flags["thr"]:
        otsu = stats.get("otsu_val")
        s = f"Otsu={otsu:.0f}" if otsu is not None else "Otsu"
        parts.append(f"thresh({s})")
    if flags["den"]:
        parts.append(
            f"noise(area<{params['noise_amin']}, "
            f"compact<{params['noise_cmp']} if area<{params['noise_amax']})"
        )
    if flags["hough"] or flags["trk"]:
        parts.append(
            f"Hough(thresh={params['hough_thr']}, "
            f"minLen={params['hough_ml']}, maxGap={params['hough_mg']})"
        )
    fig.suptitle("  |  ".join(parts), color="#cccccc",
                 fontsize=8, family="monospace", y=0.99)

    x = np.arange(256)

    ax = axes[0]
    ax.set_title("Pixel Intensity Distribution")
    ax.set_xlabel("intensity")
    ax.set_ylabel("count (log)")
    ax.set_yscale("log")
    if "raw_hist" in stats:
        ax.plot(x, np.maximum(stats["raw_hist"], 1),
                color="#888888", lw=0.8, label="raw")
    if "fog_hist" in stats:
        ax.plot(x, np.maximum(stats["fog_hist"], 1),
                color="#4488ff", lw=0.8, label="after fog")
    if "otsu_val" in stats:
        ax.axvline(stats["otsu_val"], color="#ff4444", lw=1, ls="--",
                   label=f"Otsu={stats['otsu_val']:.0f}")
    ax.legend(fontsize=7, facecolor="#222", edgecolor="#444",
              labelcolor="#ccc")

    ax = axes[1]
    ax.set_title("Blob Area Distribution")
    ax.set_xlabel("area (px, log scale)")
    ax.set_ylabel("count (log)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    bins = np.logspace(0, 5, 60)
    if "blob_areas_before" in stats and stats["blob_areas_before"]:
        ax.hist(stats["blob_areas_before"], bins=bins, color="#888888",
                alpha=0.7, label=f"before ({len(stats['blob_areas_before'])})")
    if "blob_areas_after" in stats and stats["blob_areas_after"]:
        ax.hist(stats["blob_areas_after"], bins=bins, color="#44aaff",
                alpha=0.7, label=f"after ({len(stats['blob_areas_after'])})")
    ax.axvline(params["noise_amin"], color="#ff8800", lw=1, ls="--",
               label=f"area={params['noise_amin']}")
    ax.axvline(params["noise_amax"], color="#ffcc00", lw=1, ls=":",
               label=f"area={params['noise_amax']}")
    ax.legend(fontsize=7, facecolor="#222", edgecolor="#444",
              labelcolor="#ccc")

    ax = axes[2]
    ax.set_title("Track Length Distribution")
    ax.set_xlabel("length (px)")
    ax.set_ylabel("count")
    if "track_lengths" in stats and stats["track_lengths"]:
        ax.hist(stats["track_lengths"], bins=40, color="#44ff88", alpha=0.85)
        ax.axvline(params["hough_ml"], color="#ff4444", lw=1, ls="--",
                   label=f"minLen={params['hough_ml']}")
        ax.legend(fontsize=7, facecolor="#222", edgecolor="#444",
                  labelcolor="#ccc")
        ax.text(0.97, 0.95, f"n={stats['n_tracks']}",
                transform=ax.transAxes, ha="right", va="top",
                color="#aaaaaa", fontsize=8)
    else:
        ax.text(0.5, 0.5, "no tracks detected", transform=ax.transAxes,
                ha="center", va="center", color="#666666")

    ax = axes[3]
    ax.set_title("Track Angle Distribution")
    ax.set_xlabel("angle (deg, 0–180)")
    ax.set_ylabel("count")
    if "track_angles" in stats and stats["track_angles"]:
        ax.hist(stats["track_angles"], bins=36, range=(0, 180),
                color="#ffaa44", alpha=0.85)
        ax.set_xlim(0, 180)
        ax.set_xticks(range(0, 181, 30))
    else:
        ax.text(0.5, 0.5, "no tracks detected", transform=ax.transAxes,
                ha="center", va="center", color="#666666")

    return fig


def create_app(root_dir: Path | str) -> Flask:
    """Create the Flask viewer app rooted at *root_dir*."""
    root = Path(root_dir).resolve()
    app = Flask(__name__)

    def _safe_resolve(subpath: str) -> Path:
        full = (root / subpath).resolve()
        if not str(full).startswith(str(root)):
            abort(403)
        return full

    def _parse_flags() -> dict:
        g = request.args.get
        return dict(
            zpj   = g("zpj",   "0") == "1",
            fog   = g("fog",   "0") == "1",
            thr   = g("thr",   "0") == "1",
            den   = g("den",   "0") == "1",
            hough = g("hough", "0") == "1",
            trk   = g("trk",   "0") == "1",
        )

    def _parse_params() -> dict:
        def i(name, default):
            try:
                return int(request.args.get(name, default))
            except (ValueError, TypeError):
                return int(default)
        return dict(
            zpj_half   = i("zpj_half",   Z_PROJ_HALF),
            fog_k      = i("fog_k",      FOG_KSIZE),
            noise_amin = i("noise_amin", NOISE_AREA_MIN),
            noise_amax = i("noise_amax", NOISE_AREA_MAX),
            noise_cmp  = i("noise_cmp",  NOISE_COMPACT),
            hough_thr  = i("hough_thr",  HOUGH_THRESH),
            hough_ml   = i("hough_ml",   HOUGH_MIN_LINE),
            hough_mg   = i("hough_mg",   HOUGH_MAX_GAP),
        )

    def _load_image(
        json_path: Path, idx: int, zpj: bool, zpj_half: int
    ) -> tuple[np.ndarray, int]:
        reader = load_spng(json_path)
        if zpj:
            lo = max(0, idx - zpj_half)
            hi = min(len(reader) - 1, idx + zpj_half)
            slices = [reader.read(i) for i in range(lo, hi + 1)]
            return np.mean(slices, axis=0).astype(np.uint8), len(reader)
        return reader.read(idx), len(reader)

    @app.route("/")
    @app.route("/view/")
    @app.route("/view/<path:subpath>")
    def viewer(subpath: str = "") -> str:
        full_path = _safe_resolve(subpath)

        if full_path.is_dir():
            current_dir  = full_path
            selected_json = None
            rel_dir_path  = subpath
        else:
            current_dir  = full_path.parent
            selected_json = full_path.name
            rel_dir_path  = os.path.dirname(subpath)

        items = sorted(os.listdir(current_dir))
        dirs  = [i for i in items if (current_dir / i).is_dir()]
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
            zpj_half=Z_PROJ_HALF,
            fog_k=FOG_KSIZE,
            noise_amin=NOISE_AREA_MIN,
            noise_amax=NOISE_AREA_MAX,
            noise_cmp=NOISE_COMPACT,
            hough_thr=HOUGH_THRESH,
            hough_ml=HOUGH_MIN_LINE,
            hough_mg=HOUGH_MAX_GAP,
        )

    @app.route("/image/<path:json_rel_path>/<int:idx>")
    def get_image(json_rel_path: str, idx: int):
        flags  = _parse_flags()
        params = _parse_params()
        try:
            img, _ = _load_image(
                _safe_resolve(json_rel_path), idx,
                flags["zpj"], params["zpj_half"],
            )
            result = _process(
                img,
                fog=flags["fog"], thr=flags["thr"],
                den=flags["den"], hough=flags["hough"], trk=flags["trk"],
                **{k: params[k] for k in (
                    "fog_k", "noise_amin", "noise_amax",
                    "noise_cmp", "hough_thr", "hough_ml", "hough_mg",
                )},
            )
            _, buf = cv2.imencode(".png", result)
            return send_file(io.BytesIO(buf.tobytes()), mimetype="image/png")
        except Exception as e:
            return str(e), 500

    @app.route("/stats/<path:json_rel_path>/<int:idx>")
    def get_stats(json_rel_path: str, idx: int):
        flags  = _parse_flags()
        params = _parse_params()
        try:
            img, n_slices = _load_image(
                _safe_resolve(json_rel_path), idx,
                flags["zpj"], params["zpj_half"],
            )
            stats = _collect_stats(
                img,
                fog=flags["fog"], thr=flags["thr"], den=flags["den"],
                hough_or_trk=flags["hough"] or flags["trk"],
                **{k: params[k] for k in (
                    "fog_k", "noise_amin", "noise_amax",
                    "noise_cmp", "hough_thr", "hough_ml", "hough_mg",
                )},
            )
            fig = _stats_figure(stats, flags, params, idx, n_slices)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                        facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            return send_file(buf, mimetype="image/png")
        except Exception as e:
            return str(e), 500

    return app


def run(
    root_dir: Path | str,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Start the viewer server."""
    create_app(root_dir).run(
        host=host, port=port, debug=False, threaded=True
    )
