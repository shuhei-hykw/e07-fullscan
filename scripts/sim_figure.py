"""Figure: one simulated decay event from Geant4 tracks to the image.

Uses one event of e07-g4-hypernuclei's embedded dataset (truth.json,
grains.npz and the rendered slices) and its Renderer, and draws, in a
crop around the capture and the hypernuclear decays:

  a  Geant4 charged tracks, sheet plane (x, y)
  b  the same seen from the side (x, depth), depth in the developed
     emulsion (z shrunk by Sh on development)
  c  the grains the sim deposits along the tracks (colour: slice,
     size: darkness)
  d  those grains alone through the optics model (defocus blur,
     transmission), one slice at the capture depth, no background
  e  the same slice of the dataset: the grains on a real background
     view (fog, beam tracks, noise of the real microscope)
  f  minimum projection of the dataset over the event's slices, with
     the true vertices

  python scripts/sim_figure.py [--event ev0021] \
    [--out docs/figures/sim_to_image.png]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                   # noqa: E402
import numpy as np                                # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toy_twograin as tg                         # noqa: E402

render = tg.render
DATASET = tg.G4 / "data/images/v19_embed_nagara_dz4"
HALF_PX = 110          # crop half width
PROJ_MARGIN = 3        # slices beyond the vertices in the projection
SIGNAL_CLS = (1, 2, 3)
FIG_W, FIG_H = 15.0, 10.0
DPI = 110
GRAIN_SIZE = 18.0
LINE_W = 1.8
VERTEX_SIZE = 70
SEED = 7
VERTEX_STYLE = {"capture": ("*", "red"),
                "HypernucleusDecay": ("o", "gold")}
NAME_COLOR = {"triton": "tab:red", "alpha": "tab:blue",
              "LLHe6": "tab:green", "hyperHe5": "tab:olive",
              "proton": "tab:orange", "pi-": "tab:purple"}
OTHER_COLOR = "tab:gray"


def crop_box(truth):
  v = [x for x in truth["vertices"]
       if x["type"] in VERTEX_STYLE and x["in_view"]]
  c = np.mean([[x["col"], x["row"]] for x in v], axis=0)
  n = truth["size_px"]
  c = np.clip(np.rint(c), HALF_PX, n - HALF_PX).astype(int)
  return c[0] - HALF_PX, c[1] - HALF_PX, v


def draw_tracks(ax, truth, x0, y0, side, dz_um, px_um):
  for t in truth["tracks"]:
    if not t["charge"]:
      continue
    p = np.array(t["polyline"], float)
    x = (p[:, 0] - x0) * px_um
    y = (p[:, 2] * dz_um) if side else (p[:, 1] - y0) * px_um
    lab = f"{t['name']} ({t['origin']})"
    ax.plot(x, y, color=NAME_COLOR.get(t["name"], OTHER_COLOR),
            lw=LINE_W, label=lab)


def draw_vertices(ax, verts, x0, y0, side, dz_um, px_um):
  for v in verts:
    m, c = VERTEX_STYLE[v["type"]]
    y = v["slice"] * dz_um if side else (v["row"] - y0) * px_um
    ax.scatter((v["col"] - x0) * px_um, y, marker=m, c=c,
               s=VERTEX_SIZE, edgecolors="k", zorder=5)


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--event", default="ev0021")
  ap.add_argument("--out", type=Path,
                  default=Path("docs/figures/sim_to_image.png"))
  args = ap.parse_args()
  ev = DATASET / args.event
  truth = json.loads((ev / "truth.json").read_text())
  g = dict(np.load(ev / "grains.npz"))
  px_um, dz_um = truth["pixel_um"], truth["physical_dz_um"]
  x0, y0, verts = crop_box(truth)
  size = 2 * HALF_PX
  ext = [0, size * px_um, size * px_um, 0]
  k_cap = int(round(verts[0]["slice"]))
  vs = [v["slice"] for v in verts]
  s_lo = max(int(np.floor(min(vs))) - PROJ_MARGIN, 0)
  s_hi = min(int(np.ceil(max(vs))) + PROJ_MARGIN, truth["n_slices"] - 1)

  sig = np.isin(g["cls"], SIGNAL_CLS)
  inside = (sig & (g["col"] >= x0) & (g["col"] < x0 + size)
            & (g["row"] >= y0) & (g["row"] < y0 + size))
  gr = np.column_stack([g["col"] - x0, g["row"] - y0, g["slice"]])

  # Signal grains alone through the optics (no background, no noise)
  opt, _, bg = tg.models()
  opt = replace(opt, size_px=size)
  bg = replace(bg, noise_sigma=0.)
  ren = render.Renderer(opt)
  rng = np.random.default_rng(SEED)
  clean = render.compose(bg.brightness,
                         ren.density(gr[sig], g["weight"][sig], k_cap),
                         bg, np.zeros((size, size)), rng,
                         opt.image_blur_px)
  reader = tg.load_spng(ev / "image.json")
  data = reader.read(k_cap)[y0:y0 + size, x0:x0 + size]
  proj = np.min([reader.read(s)[y0:y0 + size, x0:x0 + size]
                 for s in range(s_lo, s_hi + 1)], axis=0)

  fig, ax = plt.subplots(2, 3, figsize=(FIG_W, FIG_H))
  a = ax[0, 0]
  draw_tracks(a, truth, x0, y0, False, dz_um, px_um)
  draw_vertices(a, verts, x0, y0, False, dz_um, px_um)
  a.set(xlim=ext[:2], ylim=ext[2:], aspect="equal",
        title="a  Geant4 tracks (sheet plane)",
        xlabel="x (um)", ylabel="y (um)")
  hd, lb = a.get_legend_handles_labels()
  keep = dict(zip(lb, hd))
  a.legend(keep.values(), keep.keys(), fontsize=7, loc="lower left")
  a = ax[0, 1]
  draw_tracks(a, truth, x0, y0, True, dz_um, px_um)
  draw_vertices(a, verts, x0, y0, True, dz_um, px_um)
  a.set(xlim=ext[:2], ylim=((s_hi + PROJ_MARGIN) * dz_um,
                            (s_lo - PROJ_MARGIN) * dz_um),
        title="b  side view (depth in developed emulsion)",
        xlabel="x (um)", ylabel="depth (um)")
  a = ax[0, 2]
  m = inside
  sc = a.scatter((g["col"][m] - x0) * px_um, (g["row"][m] - y0) * px_um,
                 c=g["slice"][m], s=GRAIN_SIZE * g["weight"][m],
                 cmap="viridis")
  draw_vertices(a, verts, x0, y0, False, dz_um, px_um)
  fig.colorbar(sc, ax=a, label="slice")
  a.set(xlim=ext[:2], ylim=ext[2:], aspect="equal",
        title=f"c  grains along the tracks ({int(m.sum())})",
        xlabel="x (um)", ylabel="y (um)")
  for a, img, t in ((ax[1, 0], clean,
                     f"d  grains through the optics, slice {k_cap}"),
                    (ax[1, 1], data,
                     f"e  on a real background view, slice {k_cap}"),
                    (ax[1, 2], proj,
                     f"f  min projection, slices {s_lo}-{s_hi}")):
    a.imshow(img, cmap="gray", extent=ext, vmin=0, vmax=255)
    a.set(title=t, xlabel="x (um)", ylabel="y (um)")
  draw_vertices(ax[1, 2], verts, x0, y0, False, dz_um, px_um)
  fig.suptitle(f"{DATASET.name}/{args.event}: {truth['channel']}  "
               f"(pixel {px_um} um, slice step {dz_um} um, "
               f"Sh {truth['shrink']})")
  fig.tight_layout()
  args.out.parent.mkdir(parents=True, exist_ok=True)
  fig.savefig(args.out, dpi=DPI)
  print(args.out)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
