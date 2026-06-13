"""Generate a 5-panel preprocessing pipeline figure (Raw through Noise Removal).

Usage:
  python scripts/make_pipeline_fig.py [TILE_STEM] [--out PATH]

TILE_STEM defaults to V00000923_L0_VX0023_VY0020_0_058.
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module.io.image_reader import SpngReader
from module.preprocess import fog_remove, otsu_binarize, remove_noise

SCAN_DIR = Path(
  "/gpfs/group/had/sks/E07/tohoku/fullscan"
  "/MOD108/PL12/tohoku-v1/AREA00/IMAGE00_AREA00"
)
ZPJ_HALF = 4
DEFAULT_TILE = "V00000923_L0_VX0023_VY0020_0_058"

LABELS = [
  "1. Raw scan",
  "2. Z-Projection",
  "3. Fog Removal",
  "4. Threshold (Otsu)",
  "5. Noise Removal",
]

BG = "#111111"
FG = "white"


def zpj(reader: SpngReader, zpj_half: int = ZPJ_HALF) -> np.ndarray:
  mid = len(reader) // 2
  lo = max(0, mid - zpj_half)
  hi = min(len(reader) - 1, mid + zpj_half)
  slices = [reader.read(i) for i in range(lo, hi + 1)]
  return np.mean(slices, axis=0).astype(np.uint8)


def pct_stretch(img: np.ndarray, lo_pct=0.5, hi_pct=99.5):
  """Return (vmin, vmax) for percentile-based display."""
  lo = float(np.percentile(img, lo_pct))
  hi = float(np.percentile(img, hi_pct))
  if hi <= lo:
    hi = lo + 1
  return lo, hi


def build_panels(reader: SpngReader):
  """Return list of (image_array, label, vmin, vmax, cmap)."""
  mid = len(reader) // 2
  raw = reader.read(mid)
  proj = zpj(reader)
  fog = fog_remove(proj)
  _, binary = otsu_binarize(fog)
  denoised = remove_noise(binary)

  panels = [
    (raw,      LABELS[0], 0,   255, "gray"),
    (proj,     LABELS[1], 0,   255, "gray"),
    (fog,      LABELS[2], *pct_stretch(fog), "gray"),
    (binary,   LABELS[3], 0,   255, "gray"),
    (denoised, LABELS[4], 0,   255, "gray"),
  ]
  return panels


def make_figure(panels, out_path: Path) -> None:
  # Layout: 2 rows × 3 cols, step 5 gets a highlighted border
  nrows, ncols = 2, 3
  fig = plt.figure(figsize=(ncols * 4.2, nrows * 4.4 + 0.3),
                   facecolor=BG)
  gs = fig.add_gridspec(
    nrows, ncols,
    hspace=0.08, wspace=0.06,
    left=0.01, right=0.99,
    top=0.93, bottom=0.01,
  )

  positions = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)]
  highlight_idx = 4  # step 5 = noise removal

  for i, (img, label, vmin, vmax, cmap) in enumerate(panels):
    r, c = positions[i]
    ax = fig.add_subplot(gs[r, c])
    ax.imshow(img, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_axis_off()

    edge_color = "#00aaff" if i == highlight_idx else "#444444"
    edge_lw = 2.0 if i == highlight_idx else 0.8
    for spine in ax.spines.values():
      spine.set_visible(True)
      spine.set_edgecolor(edge_color)
      spine.set_linewidth(edge_lw)

    ax.set_title(label, color=FG, fontsize=11, pad=4,
                 fontfamily="monospace", fontweight="bold")

  # empty bottom-right cell: show a brief legend / note
  ax_empty = fig.add_subplot(gs[1, 2])
  ax_empty.set_facecolor(BG)
  ax_empty.set_axis_off()
  note = (
    "Preprocessing pipeline\n"
    "──────────────────────\n"
    "Steps 1–5 precede\n"
    "graph analysis.\n\n"
    "Highlighted: output\n"
    "passed to next stage."
  )
  ax_empty.text(
    0.5, 0.5, note,
    transform=ax_empty.transAxes,
    ha="center", va="center",
    color="#aaaaaa", fontsize=9.5,
    fontfamily="monospace",
    linespacing=1.6,
  )

  out_path.parent.mkdir(parents=True, exist_ok=True)
  fig.savefig(out_path, dpi=150, bbox_inches="tight",
              facecolor=BG)
  plt.close(fig)
  print(f"Saved: {out_path}")


def main() -> None:
  ap = argparse.ArgumentParser()
  ap.add_argument("tile", nargs="?", default=DEFAULT_TILE)
  ap.add_argument("--out", default="docs/pipeline.png")
  args = ap.parse_args()

  json_path = SCAN_DIR / f"{args.tile}.json"
  if not json_path.exists():
    sys.exit(f"Not found: {json_path}")

  print(f"Tile: {args.tile}")
  reader = SpngReader(json_path)
  print(f"Slices: {len(reader)}")

  panels = build_panels(reader)
  out = ROOT / args.out
  make_figure(panels, out)


if __name__ == "__main__":
  main()
