#!/usr/bin/env python
"""Merge per-slice vertex candidates and extract raw image crops.

Usage:
  python scripts/merge_vertices.py \
    --input  results/vertices.parquet \
    --output results/vertices_merged.parquet \
    --crops  results/vertex_crops \
    --min-slices 3 \
    --min-tracks 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Merge vertex slices and extract image crops")
    ap.add_argument("--input",       type=Path,
                    default=Path("results/vertices.parquet"))
    ap.add_argument("--output",      type=Path,
                    default=Path("results/vertices_merged.parquet"))
    ap.add_argument("--crops",       type=Path, default=None,
                    help="Directory to save vertex image crops "
                         "(skip if omitted)")
    ap.add_argument("--data-dir",    type=Path,
                    default=Path("/gpfs/group/had/sks/E07/tohoku/fullscan"
                                 "/MOD108/PL12/tohoku-v1/AREA00"
                                 "/IMAGE00_AREA00"))
    ap.add_argument("--min-slices",  type=int,   default=2,
                    help="Min slice count for merged vertex")
    ap.add_argument("--min-tracks",  type=int,   default=8,
                    help="Min n_tracks_max to save crop")
    ap.add_argument("--crop-half",   type=int,   default=256,
                    help="Half-size of image crop in pixels")
    ap.add_argument("--eps-xy",      type=float, default=50.0,
                    help="XY clustering radius (px)")
    ap.add_argument("--max-crops",   type=int,   default=None,
                    help="Max number of crops to save (for testing)")
    args = ap.parse_args()

    import numpy as np
    import pandas as pd
    import cv2

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from e07fullscan.clustering import merge_vertex_slices
    from e07fullscan.io import SpngReader
    from e07fullscan.utils import (
      make_run_id, build_run_meta,
      save_run_json, save_parquet_with_meta,
    )

    run_id = make_run_id()
    run_params = {k: str(v) for k, v in vars(args).items()}
    run_meta = build_run_meta(run_id, __file__, run_params)
    print(f"run_id: {run_id}")

    print(f"Loading {args.input} …", flush=True)
    df = pd.read_parquet(args.input)
    print(f"  {len(df):,} raw vertex candidates, "
          f"{df['view_id'].nunique()} views")

    print("Merging across slices …", flush=True)
    mdf = merge_vertex_slices(df, eps_xy=args.eps_xy,
                              min_slices=args.min_slices)
    print(f"  → {len(mdf):,} merged vertices")

    print("n_tracks_max distribution (top):")
    vc = mdf['n_tracks_max'].value_counts().sort_index(ascending=False)
    for n, c in vc.head(20).items():
        print(f"  {n:3d}: {c:>6,}")

    print(f"\nn_slices distribution:")
    vs = mdf['n_slices'].value_counts().sort_index()
    for n, c in vs.items():
        print(f"  {n:3d}: {c:>6,}")

    save_parquet_with_meta(mdf, args.output, run_meta)
    json_path = save_run_json(run_meta, args.output)
    print(f"\nSaved → {args.output}")
    print(f"Run metadata → {json_path}")

    if args.crops is None:
        return

    # extract image crops for high-multiplicity vertices
    candidates = mdf[
        mdf['n_tracks_max'] >= args.min_tracks
    ].sort_values('n_tracks_max', ascending=False)

    if args.max_crops:
        candidates = candidates.head(args.max_crops)

    args.crops.mkdir(parents=True, exist_ok=True)
    save_run_json(run_meta, args.crops)
    print(f"\nExtracting {len(candidates)} image crops → {args.crops}")

    saved = 0
    for rank, (_, row) in enumerate(candidates.iterrows()):
        json_path = Path(row['view_id'])
        if not json_path.exists():
            continue
        try:
            reader = SpngReader(json_path)
            stack  = reader.read_stack()
        except Exception as e:
            print(f"  WARNING: {json_path.name}: {e}", file=sys.stderr)
            continue

        # z-projection centred on z_mean
        n_sl = len(reader)
        z_vals = np.array([e.z for e in reader.entries])
        best_idx = int(np.argmin(np.abs(z_vals - row['z_mean'])))
        half = 4
        lo = max(0, best_idx - half)
        hi = min(n_sl - 1, best_idx + half)
        img = stack[lo:hi + 1].mean(axis=0).astype(np.uint8)

        vx = int(round(row['vx_px']))
        vy = int(round(row['vy_px']))
        s  = args.crop_half
        x0 = max(0, vx - s); y0 = max(0, vy - s)
        x1 = min(img.shape[1], vx + s)
        y1 = min(img.shape[0], vy + s)
        crop = img[y0:y1, x0:x1].copy()

        # mark vertex
        vis = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        cv2.circle(vis, (vx - x0, vy - y0), 12, (0, 255, 0), 2)
        cv2.putText(
            vis,
            f"n={row['n_tracks_max']} sl={row['n_slices']}",
            (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
        )

        view_tag = json_path.stem.split('_L0')[0]
        fname = (f"rank{rank+1:04d}_{view_tag}"
                 f"_n{int(row['n_tracks_max'])}"
                 f"_sl{int(row['n_slices'])}.png")
        cv2.imwrite(str(args.crops / fname), vis)
        saved += 1

    print(f"Saved {saved} crops.")


if __name__ == "__main__":
    main()
