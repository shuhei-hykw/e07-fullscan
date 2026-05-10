#!/usr/bin/env python
"""Crop raw SPNG images around vertex positions for visual inspection.

Each output PNG shows a 3-panel strip:
  [raw image] | [fog-removed] | [binary (track map)]
with a red crosshair marking the vertex centre.

Usage:
  python scripts/crop_vertices.py \
    --vertices results/vertices_merged.parquet \
    --output-dir results/vertex_crops_raw/ \
    --n-samples 20 \
    --min-tracks 8

Sampling order: descending n_tracks_max (highest-confidence first).
Use --shuffle to draw a random subset instead.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


def _load_zproject(
    json_path: Path, z_target: float, zpj_half: int, zpj_mode: str = "mean"
) -> tuple[np.ndarray, int]:
    """Load a z-projection centred on z_target.

    zpj_half: half-range in slices; -1 = use all slices.
    zpj_mode: 'mean' (average) or 'max' (maximum intensity projection).
    Returns (projected_image, centre_slice_index).
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from e07fullscan.io.image_reader import SpngReader
    reader = SpngReader(json_path)
    zpos = reader.z_positions()
    centre = int(np.argmin(np.abs(zpos - z_target)))
    if zpj_half < 0:
        lo, hi = 0, len(reader) - 1
    else:
        lo = max(0, centre - zpj_half)
        hi = min(len(reader) - 1, centre + zpj_half)
    stack = np.stack(
        [reader.read(i).astype(np.float32) for i in range(lo, hi + 1)],
        axis=0,
    )
    if zpj_mode == "max":
        proj = stack.max(axis=0).astype(np.uint8)
    else:
        proj = stack.mean(axis=0).astype(np.uint8)
    return proj, centre


def _fog_remove(img: np.ndarray, fog_ksize: int = 51) -> np.ndarray:
    """Return fog-removed float image (not binarised)."""
    k = fog_ksize if fog_ksize % 2 == 1 else fog_ksize + 1
    blurred = cv2.GaussianBlur(img.astype(np.float32), (k, k), 0)
    diff = blurred - img.astype(np.float32)
    diff = np.clip(diff, 0, None)
    hi = diff.max()
    if hi > 0:
        diff = (diff / hi * 255).astype(np.uint8)
    return diff.astype(np.uint8)


def _binary(img: np.ndarray, fog_ksize: int = 51) -> np.ndarray:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from e07fullscan.tracking._finder import preprocess
    return preprocess(img, fog_ksize=fog_ksize)


def _threshold_only(fog_img: np.ndarray) -> np.ndarray:
    """Otsu threshold + noise removal on an already fog-removed image."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import cv2 as _cv2
    _, binary = _cv2.threshold(
        fog_img, 0, 255, _cv2.THRESH_BINARY | _cv2.THRESH_OTSU
    )
    return binary


def _crop_and_pad(
    img: np.ndarray, cx: int, cy: int, half: int
) -> np.ndarray:
    """Crop [cy-half:cy+half, cx-half:cx+half], zero-padding if out of bounds."""
    H, W = img.shape[:2]
    y0, y1 = cy - half, cy + half
    x0, x1 = cx - half, cx + half
    pad_top    = max(0, -y0)
    pad_bottom = max(0, y1 - H)
    pad_left   = max(0, -x0)
    pad_right  = max(0, x1 - W)
    y0c, y1c = max(0, y0), min(H, y1)
    x0c, x1c = max(0, x0), min(W, x1)
    patch = img[y0c:y1c, x0c:x1c]
    if patch.ndim == 2:
        patch = np.pad(
            patch,
            ((pad_top, pad_bottom), (pad_left, pad_right)),
            constant_values=0,
        )
    else:
        patch = np.pad(
            patch,
            ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)),
            constant_values=0,
        )
    return patch


def _draw_crosshair(img_bgr: np.ndarray, half: int) -> np.ndarray:
    """Draw red edge ticks + a small filled dot at the centre.

    The dot marks the exact vertex position without obscuring the surrounding
    structure; edge ticks help locate it at a glance.
    """
    out = img_bgr.copy()
    cx, cy = half, half
    sz = img_bgr.shape[0]
    tick  = max(8, sz // 12)
    thick = max(1, sz // 120)
    color = (0, 0, 255)   # red in BGR
    # edge ticks
    cv2.line(out, (cx, 0),      (cx, tick),      color, thick)
    cv2.line(out, (cx, sz - 1), (cx, sz - tick), color, thick)
    cv2.line(out, (0, cy),      (tick, cy),       color, thick)
    cv2.line(out, (sz - 1, cy), (sz - tick, cy),  color, thick)
    # small centre dot (radius 1 px)
    cv2.circle(out, (cx, cy), 1, color, -1)
    return out


def _fog_remove_max(
    json_path: Path, z_target: float, fog_ksize: int = 51
) -> np.ndarray:
    """Max projection of fog-removed images across all slices.

    After fog removal tracks are bright; MIP across all slices shows every
    track regardless of depth.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from e07fullscan.io.image_reader import SpngReader
    reader = SpngReader(json_path)
    acc = None
    for i in range(len(reader)):
        fog = _fog_remove(reader.read(i), fog_ksize=fog_ksize).astype(np.float32)
        if acc is None:
            acc = fog
        else:
            acc = np.maximum(acc, fog)
    return acc.astype(np.uint8)


def _load_min_projection(json_path: Path) -> np.ndarray:
    """Minimum intensity projection across all slices, contrast-stretched.

    In nuclear emulsion the raw image has dark tracks on a gray background.
    Taking the minimum over all slices makes every track position dark
    regardless of which slice it appears in.  Contrast stretching ensures
    the full 0-255 dynamic range is used for clear visualisation.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from e07fullscan.io.image_reader import SpngReader
    reader = SpngReader(json_path)
    acc = None
    for i in range(len(reader)):
        img = reader.read(i).astype(np.float32)
        if acc is None:
            acc = img
        else:
            acc = np.minimum(acc, img)
    # contrast stretch to full 0-255 range
    lo, hi = float(acc.min()), float(acc.max())
    if hi > lo:
        acc = (acc - lo) / (hi - lo) * 255.0
    return acc.astype(np.uint8)


def make_strip(
    raw: np.ndarray,
    fog: np.ndarray,
    binary: np.ndarray,
    cx: int, cy: int, half: int,
) -> np.ndarray:
    panels = []
    for img in (raw, fog, binary):
        patch = _crop_and_pad(img, cx, cy, half)
        bgr = cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
        bgr = _draw_crosshair(bgr, half)
        panels.append(bgr)
    strip = np.concatenate(panels, axis=1)
    # label each panel
    for i, label in enumerate(("RAW", "FOG-REMOVED", "BINARY")):
        x = i * 2 * half + 4
        cv2.putText(
            strip, label, (x, 18),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 0), 1,
            cv2.LINE_AA,
        )
    return strip


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Crop raw SPNG images at vertex positions"
    )
    ap.add_argument(
        "--vertices", type=Path,
        default=Path("results/vertices_merged.parquet"),
    )
    ap.add_argument(
        "--output-dir", type=Path,
        default=Path("results/vertex_crops_raw"),
    )
    ap.add_argument("--n-samples",  type=int,   default=20)
    ap.add_argument("--crop-size",  type=int,   default=300,
                    help="Crop half-size in pixels (total = 2×crop-size)")
    ap.add_argument("--min-tracks", type=int,   default=3)
    ap.add_argument("--min-slices", type=int,   default=1)
    ap.add_argument("--max-tracks", type=int,   default=None)
    ap.add_argument("--shuffle",    action="store_true",
                    help="Random sample instead of top-n by n_tracks_max")
    ap.add_argument("--seed",       type=int,   default=42)
    ap.add_argument("--fog-ksize",  type=int,   default=51)
    ap.add_argument("--zpj-half",   type=int,   default=4,
                    help="Z-projection half-range (slices); "
                         "-1 = all slices")
    ap.add_argument("--zpj-mode",   default="mean",
                    choices=["mean", "max"],
                    help="Projection mode: mean or max (MIP)")
    args = ap.parse_args()

    df = pd.read_parquet(args.vertices)
    print(f"Loaded {len(df):,} merged vertices")

    sel = df[df['n_tracks_max'] >= args.min_tracks]
    if args.min_slices > 1:
        sel = sel[sel['n_slices'] >= args.min_slices]
    if args.max_tracks is not None:
        sel = sel[sel['n_tracks_max'] <= args.max_tracks]

    if args.shuffle:
        sel = sel.sample(
            min(args.n_samples, len(sel)), random_state=args.seed
        )
    else:
        sel = sel.nlargest(args.n_samples, 'n_tracks_max')

    print(f"Sampling {len(sel)} vertices "
          f"(n_tracks_max {sel['n_tracks_max'].min()}–"
          f"{sel['n_tracks_max'].max()})")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    half = args.crop_size

    for rank, (_, row) in enumerate(sel.iterrows(), 1):
        json_path = Path(row['view_id'])
        view_tag  = json_path.stem
        cx = int(round(float(row['vx_px'])))
        cy = int(round(float(row['vy_px'])))
        n_tr = int(row['n_tracks_max'])
        n_sl = int(row['n_slices'])
        z_target = float(row['z_mean'])

        try:
            # min projection: dark tracks accumulate across all slices
            raw_img    = _load_min_projection(json_path)
            slice_idx  = 0
            fog_img    = _fog_remove(raw_img, fog_ksize=args.fog_ksize)
            binary_img = _binary(raw_img,     fog_ksize=args.fog_ksize)
        except Exception as e:
            print(f"  [SKIP] {view_tag}: {e}")
            continue

        strip = make_strip(raw_img, fog_img, binary_img, cx, cy, half)

        fname = (
            f"{rank:03d}_{view_tag}"
            f"_n{n_tr}_sl{n_sl}"
            f"_z{slice_idx}"
            f"_x{cx}_y{cy}.png"
        )
        out_path = args.output_dir / fname
        cv2.imwrite(str(out_path), strip)
        print(f"  [{rank:3d}] {fname}")

    print(f"\nSaved {len(sel)} crops → {args.output_dir}/")


if __name__ == "__main__":
    main()
