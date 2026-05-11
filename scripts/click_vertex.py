"""Click on reaction vertex in a specials image to get pixel coordinates.

Usage:
  python scripts/click_vertex.py /path/to/specials_x20/T011/0000.png
  python scripts/click_vertex.py /path/to/specials_x20/T011/  # uses 0000.png

Click on the reaction vertex — coordinates are printed to terminal.
Press Enter in terminal to close.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np


def _load_image(path: Path) -> np.ndarray:
  if path.is_dir():
    path = path / "0000.png"
  img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
  if img is None:
    raise FileNotFoundError(f"Cannot load: {path}")
  return img


def main() -> None:
  if len(sys.argv) < 2:
    print("Usage: python click_vertex.py <image_or_dir>")
    sys.exit(1)

  path = Path(sys.argv[1])
  img = _load_image(path)

  # min projection across z if directory given — show all tracks at once
  if path.is_dir():
    pngs = sorted(path.glob("*.png"))
    if len(pngs) > 1:
      stack = [cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) for p in pngs]
      stack = [s for s in stack if s is not None]
      img = np.min(np.stack(stack, axis=0), axis=0)
      print(f"Min projection over {len(stack)} slices")

  clicks: list[tuple[int, int]] = []

  def onclick(event: matplotlib.backend_bases.MouseEvent) -> None:
    if event.xdata is None or event.ydata is None:
      return
    x, y = int(round(event.xdata)), int(round(event.ydata))
    clicks.append((x, y))
    print(f"  click {len(clicks):2d}: x={x}, y={y}")
    ax.plot(x, y, "r+", markersize=14, markeredgewidth=2)
    fig.canvas.draw()

  fig, ax = plt.subplots(figsize=(9, 9))
  ax.imshow(img, cmap="gray", vmin=np.percentile(img, 1),
        vmax=np.percentile(img, 99))
  ax.set_title(f"{path.name}  —  click on reaction vertex (printed to terminal)")
  fig.canvas.mpl_connect("button_press_event", onclick)

  plt.tight_layout()
  plt.show()

  if clicks:
    print("\n--- recorded clicks ---")
    for i, (x, y) in enumerate(clicks, 1):
      print(f"  {i}: x={x}, y={y}")


if __name__ == "__main__":
  main()
