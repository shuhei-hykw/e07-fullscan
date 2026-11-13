"""Specials events resampled to the full-scan pixel (0.507 um/px).

The specials (specials_x20, tests/specials_gt.json) are the only real
events with known vertices, but they were taken at 0.289 um/px while the
full scan is 0.507 um/px, so detectors tuned or fixed for the full scan
cannot be checked on them as they are. This writes each event with known
truth, area-averaged down to OUT_PX_UM (2048 -> 1167 px; x/y only, z
unchanged), keeping N_SLICES slices around the clicked one (the full
scan's depth), into OUT/<event>/ with an image.json (AffineP2S scaled)
and a gt.json (click scaled; slice relative to the kept window). The
click is good to +-50-100 px at 0.289, i.e. +-15-30 um.

  python scripts/specials_resample.py   # -> results/specials_0507/
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
SPECIALS = REPO.parent / "specials_x20"
GT = REPO / "tests/specials_gt.json"
OUT = REPO / "results/specials_0507"
OUT_PX_UM = 0.507
N_SLICES = 58
MM_PER_UM = 1e-3


def main():
  gt = json.loads(GT.read_text())["events"]
  for ev, g in gt.items():
    src = json.loads((SPECIALS / ev / "image.json").read_text())
    in_px_um = src["AffineP2S"][0] / MM_PER_UM
    f = in_px_um / OUT_PX_UM
    ims = src["Images"]
    lo = int(np.clip(g["z_slice"] - N_SLICES // 2, 0,
                     max(len(ims) - N_SLICES, 0)))
    keep = ims[lo:lo + N_SLICES]
    d = OUT / ev
    d.mkdir(parents=True, exist_ok=True)
    for im in keep:
      img = Image.open(SPECIALS / ev / im["Path"])
      size = (round(img.width * f), round(img.height * f))
      img.resize(size, Image.Resampling.BOX).save(d / im["Path"])
    out = dict(src, Images=keep)
    out["AffineP2S"] = [a * OUT_PX_UM / in_px_um if i < 4 else a
                        for i, a in enumerate(src["AffineP2S"])]
    out["ImageType"] = dict(src["ImageType"], Width=size[0],
                            Height=size[1])
    out["Resampled"] = {"from": str(SPECIALS / ev), "factor": f,
                        "first_slice": lo}
    (d / "image.json").write_text(json.dumps(out, indent=1))
    (d / "gt.json").write_text(json.dumps(
      {"vx": g["vx"] * f, "vy": g["vy"] * f,
       "z_slice": g["z_slice"] - lo, "tol_xy_um": 30.0}, indent=1))
    print(f"{ev}: {len(keep)} slices from {lo}, {size[0]} px")


if __name__ == "__main__":
  main()
