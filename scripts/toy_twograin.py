"""Two-grain toy stacks for the dog3d depth suppression.

Grains are rendered with the e07-g4-hypernuclei Renderer and the v19
optics on a flat, noisy field; the DoG threshold is the median per-slice
threshold measured on real-size v19 tune views (median + K robust sigma
is set by the whole view, not by this small empty patch).

  python scripts/toy_twograin.py   # -> results/pointcloud_eval/toy_twograin
"""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter
from scipy.optimize import linear_sum_assignment

FS = Path.home() / "work/e07-fullscan"
G4 = Path.home() / "work/e07-g4-hypernuclei"
sys.path.insert(0, str(FS))
sys.path.insert(0, str(FS / "scripts"))
import importlib.util                             # noqa: E402
import eval_pointcloud as ep                      # noqa: E402
from module.reader import load_spng               # noqa: E402


def _sim_package():
  """The sim repo's `module` package under another name (both repos
  call their package `module`)."""
  spec = importlib.util.spec_from_file_location(
    "simmodule", G4 / "module/__init__.py",
    submodule_search_locations=[str(G4 / "module")])
  pkg = importlib.util.module_from_spec(spec)
  sys.modules["simmodule"] = pkg
  spec.loader.exec_module(pkg)
  return importlib.import_module("simmodule.synth.calibrate")


_cal = _sim_package()
render = _cal.render
apply_values, load_model = _cal.apply_values, _cal.load_model

OUT = FS / "results/pointcloud_eval/toy_twograin"
MODEL = G4 / "output/image_model_v19_dz4.json"
TUNE = G4 / "data/images/v19_synth_tune_dz4"
SIZE = 96
N_SL = 9
MID = N_SL // 2
CX = SIZE / 2
N_SEED = 40
MATCH_PX = 2.5
MATCH_SL = 1
KS = (2.0, 3.0)
THR_VIEWS = 3
THR_SLICES = (10, 30, 50)


def models():
  v = load_model(MODEL)
  o = replace(render.Optics(), size_px=SIZE, n_slices=N_SL, dz_um=4.0)
  return apply_values(v, o, render.Emulsion(), render.Background())


def view_thresholds():
  """Median over real-size tune slices of median + k MAD-sigma."""
  out = {k: [] for k in KS}
  for ev in sorted(TUNE.glob("ev*"))[:THR_VIEWS]:
    rd = load_spng(ev / "image.json")
    for s in THR_SLICES:
      r = ep.dog_response(rd.read(s))
      med = np.median(r)
      mad = np.median(np.abs(r - med)) * ep._MAD_TO_SIGMA
      for k in KS:
        out[k].append(med + k * mad)
  return {k: float(np.median(v)) for k, v in out.items()}


def stack(grains, weights, opt, bg, rng):
  ren = render.Renderer(opt)
  fixed = rng.normal(0., bg.fixed_noise_sigma, (SIZE, SIZE))
  return [render.compose(bg.brightness, ren.density(grains, weights, k),
                         bg, fixed, rng, opt.image_blur_px)
          for k in range(N_SL)]


def dog3d(imgs, thr):
  r = np.stack([ep.dog_response(i) for i in imgs])
  mx = np.stack([maximum_filter(x, size=ep.DOG_PEAK_PX) for x in r])
  peak = (r == mx) & (r > thr)
  nb = np.full_like(mx, -np.inf)
  nb[1:] = np.maximum(nb[1:], mx[:-1])
  nb[:-1] = np.maximum(nb[:-1], mx[1:])
  return (np.argwhere(peak), np.argwhere(peak & (r >= nb)))


def score(pts, grains):
  """One-to-one match: found mask per grain, z error, extra points."""
  if len(pts) == 0:
    return np.zeros(len(grains), bool), np.full(len(grains), np.nan), 0
  p = pts[:, [2, 1, 0]].astype(float)          # col, row, slice
  dxy = np.hypot(p[:, None, 0] - grains[None, :, 0],
                 p[:, None, 1] - grains[None, :, 1])
  dz = p[:, None, 2] - grains[None, :, 2]
  ok = (dxy <= MATCH_PX) & (np.abs(dz) <= MATCH_SL + 0.5)
  cost = np.where(ok, dxy + np.abs(dz), 1e6)
  ri, ci = linear_sum_assignment(cost)
  good = ok[ri, ci]
  found = np.zeros(len(grains), bool)
  zerr = np.full(len(grains), np.nan)
  found[ci[good]] = True
  zerr[ci[good]] = dz[ri[good], ci[good]]
  near = ok.any(axis=1)
  return found, zerr, int(near.sum() - good.sum())


def run(cfgs, thr, opt, bg):
  rows = []
  for name, dxy, dsl, wa, wb, z0 in cfgs:
    acc = {k: {"f": [], "z": [], "x": []} for k in ("dog", "dog3d")}
    for seed in range(N_SEED):
      rng = np.random.default_rng(seed)
      jit = rng.uniform(-0.5, 0.5, 2)
      g = np.array([[CX + jit[0], CX + jit[1], z0],
                    [CX + jit[0] + dxy, CX + jit[1], z0 + dsl]])
      w = np.array([wa, wb])
      if wb == 0:
        g, w = g[:1], w[:1]
      d2, d3 = dog3d(stack(g, w, opt, bg, rng), thr)
      for k, pts in (("dog", d2), ("dog3d", d3)):
        f, z, x = score(pts, g)
        acc[k]["f"].append(f)
        acc[k]["z"].append(z)
        acc[k]["x"].append(x)
    for k, a in acc.items():
      f = np.array(a["f"])
      z = np.array(a["z"])
      rows.append(dict(cfg=name, dxy=dxy, dsl=dsl, wa=wa, wb=wb, z0=z0,
                       method=k, effA=f[:, 0].mean(),
                       effB=f[:, 1].mean() if f.shape[1] > 1 else np.nan,
                       both=f.all(axis=1).mean(),
                       zbiasA=np.nanmean(z[:, 0]),
                       extra=np.mean(a["x"])))
  return rows


def main():
  import pandas as pd
  opt, _, bg = models()
  thrs = view_thresholds()
  print("view thresholds", thrs, flush=True)
  cfgs = []
  # Isolated grains: darkness, fractional focus, stack end
  for wa in (0.25, 0.5, 1.0, 2.0):
    for z0 in (MID, MID + 0.5):
      cfgs.append(("single", 0, 0, wa, 0, z0))
  for z0 in (0, 0.5, N_SL - 1):
    cfgs.append(("end", 0, 0, 1.0, 0, z0))
  for dxy in (0, 1, 2, 3, 4, 6, 10):
    for dsl in (0, 1, 2):
      for wb in (1.0, 0.5):
        cfgs.append(("pair", dxy, dsl, 1.0, wb, MID))
  out = []
  for k, thr in thrs.items():
    for r in run(cfgs, thr, opt, bg):
      out.append(dict(r, K=k))
  df = pd.DataFrame(out)
  OUT.mkdir(parents=True, exist_ok=True)
  df.to_csv(OUT / "toy_twograin.csv", index=False)
  pd.set_option("display.width", 200)
  print(df.round(2).to_string(index=False))


if __name__ == "__main__":
  main()
