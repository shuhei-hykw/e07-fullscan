"""Click on reaction vertex in a specials image to get pixel coordinates.

Usage:
  # single slice (records slice index + z coordinate from image.json)
  python scripts/click_vertex.py /path/to/specials_x20/T011/0025.png

  # directory: shows min projection over all slices
  python scripts/click_vertex.py /path/to/specials_x20/T011/

Click on the reaction vertex — coordinates are printed to terminal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np


def _load_z_info(
  png_path: Path,
) -> tuple[int, float] | tuple[None, None]:
  """Return (slice_idx, z_um) if image.json is present, else (None, None)."""
  json_path = png_path.parent / "image.json"
  if not json_path.exists():
    return None, None
  try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from module.io import load_spng
    reader = load_spng(json_path)
    stem = png_path.stem          # e.g. "0025"
    idx = int(stem)
    z_um = float(reader.z_positions()[idx])
    return idx, z_um
  except Exception:
    return None, None


def main() -> None:
  if len(sys.argv) < 2:
    print("Usage: python click_vertex.py <image_or_dir>")
    sys.exit(1)

  path = Path(sys.argv[1])
  is_dir = path.is_dir()
  z_slice: int | None = None
  z_um: float | None = None

  if is_dir:
    pngs = sorted(path.glob("*.png"))
    if not pngs:
      print(f"No PNG files in {path}")
      sys.exit(1)
    stack = [cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) for p in pngs]
    stack = [s for s in stack if s is not None]
    img = np.min(np.stack(stack, axis=0), axis=0)
    title = f"{path.name} (min-proj {len(stack)} slices)"
    print(f"Min projection over {len(stack)} slices")
    print("  Z info not recorded for directory mode — open a specific slice for Z.")
  else:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
      raise FileNotFoundError(f"Cannot load: {path}")
    z_slice, z_um = _load_z_info(path)
    title = path.name
    if z_slice is not None:
      print(f"Slice {z_slice}  z={z_um:.2f} um")
      title += f"  slice={z_slice}  z={z_um:.2f}μm"

  clicks: list[dict] = []

  def onclick(event: matplotlib.backend_bases.MouseEvent) -> None:
    if event.xdata is None or event.ydata is None:
      return
    x, y = int(round(event.xdata)), int(round(event.ydata))
    entry: dict = {"x": x, "y": y}
    if z_slice is not None:
      entry["z_slice"] = z_slice
      entry["z_um"] = z_um
    clicks.append(entry)
    print(f"  click {len(clicks):2d}: x={x}, y={y}"
          + (f"  z={z_um:.2f}um" if z_um is not None else ""))
    ax.plot(x, y, "r+", markersize=14, markeredgewidth=2)
    fig.canvas.draw()

  fig, ax = plt.subplots(figsize=(9, 9))
  ax.imshow(img, cmap="gray", vmin=np.percentile(img, 1),
            vmax=np.percentile(img, 99))
  ax.set_title(title)
  fig.canvas.mpl_connect("button_press_event", onclick)

  plt.tight_layout()
  plt.show()

  if clicks:
    print("\n--- recorded clicks ---")
    for i, c in enumerate(clicks, 1):
      zstr = f"  z={c['z_um']:.2f}um" if "z_um" in c else ""
      print(f"  {i}: x={c['x']}, y={c['y']}{zstr}")
    result = {
      "image": str(path),
      "clicks": clicks,
    }
    print("\nJSON:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
  main()
