#!/usr/bin/env python
"""Find vertex candidates from track parquet (merged or single chunk).

Single file:
  python scripts/find_vertices.py \
    --input  results/merged.parquet \
    --output results/vertices.parquet

KEKCC batch (one chunk per job):
  python scripts/find_vertices.py \
    --input  results/chunk_0001.parquet \
    --output results/vertex_chunks/vertex_0001.parquet \
    --min-tracks-out 5
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Vertex finder for module")
    ap.add_argument("--input",  type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--min-tracks",     type=int,   default=3,
                    help="Min tracks to form a vertex (intersection cut)")
    ap.add_argument("--min-tracks-out", type=int,   default=3,
                    help="Min tracks in saved output (post-filter)")
    ap.add_argument("--max-impact",     type=float, default=30.0,
                    help="Max perpendicular distance to vertex (px)")
    ap.add_argument("--max-ep",         type=float, default=150.0,
                    help="Max nearest-endpoint distance to vertex (px)")
    ap.add_argument("--max-ep-frac",    type=float, default=0.5,
                    help="Max ep as fraction of track length (0=disable)")
    ap.add_argument("--min-intens",     type=float, default=12.0,
                    help="Quality cut on mean_intens")
    ap.add_argument("--min-len",        type=float, default=100.0,
                    help="Quality cut on length_px")
    ap.add_argument("--eps",            type=float, default=25.0,
                    help="Clustering radius (px)")
    ap.add_argument("--beam-angle-cut",   type=float, default=0.0,
                    help="Exclude tracks with angle_deg < cut or "
                         "> 180-cut (beam-parallel removal, deg)")
    ap.add_argument("--min-angle-spread", type=float, default=0.0,
                    help="Min angular spread of contributing tracks (deg);"
                         " rejects heavy-particle fake vertices; 0=disable")
    ap.add_argument("--views",           type=int,   default=None,
                    help="Limit to N views (for testing)")
    args = ap.parse_args()

    import pandas as pd
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from module.clustering import find_vertices
    from module.utils import (
      make_run_id, build_run_meta,
      save_run_json, save_parquet_with_meta,
    )

    run_id = make_run_id()
    run_params = {k: str(v) for k, v in vars(args).items()}
    run_meta = build_run_meta(run_id, __file__, run_params)
    print(f"run_id: {run_id}")

    print(f"Loading {args.input} …", flush=True)
    df = pd.read_parquet(args.input)
    n_views = df['view_id'].nunique()
    print(f"  {len(df):,} tracks, {n_views} views")

    if args.views:
        vids = df['view_id'].unique()[:args.views]
        df = df[df['view_id'].isin(vids)]
        print(f"  Limiting to {args.views} views → {len(df):,} tracks")

    sel_n = int(((df['mean_intens'] >= args.min_intens) &
                 (df['length_px']   >= args.min_len)).sum())
    print(f"  After quality cuts: {sel_n:,} tracks "
          f"({sel_n/len(df)*100:.1f}%)", flush=True)

    print("Finding vertices …", flush=True)
    t0 = time.time()
    vdf = find_vertices(
        df,
        min_tracks=args.min_tracks,
        max_impact=args.max_impact,
        max_ep=args.max_ep,
        max_ep_frac=args.max_ep_frac,
        min_intens=args.min_intens,
        eps_px=args.eps,
        min_len_px=args.min_len,
        beam_angle_cut=args.beam_angle_cut,
        min_angle_spread=args.min_angle_spread,
    )
    elapsed = time.time() - t0

    if vdf.empty:
        print("No vertices found.", file=sys.stderr)
        save_parquet_with_meta(vdf, args.output, run_meta)
        save_run_json(run_meta, args.output)
        return

    # output filter
    vdf = vdf[vdf['n_tracks'] >= args.min_tracks_out]

    print(f"  Found {len(vdf):,} vertex candidates "
          f"(n_tracks>={args.min_tracks_out}) in {elapsed:.1f}s")
    print("  n_tracks distribution:")
    print(vdf['n_tracks'].value_counts().sort_index().to_string(dtype=False))

    save_parquet_with_meta(vdf, args.output, run_meta)
    json_path = save_run_json(run_meta, args.output)
    print(f"Saved → {args.output}")
    print(f"Run metadata → {json_path}")


if __name__ == "__main__":
    main()
