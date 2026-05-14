#!/usr/bin/env bash
# Full pipeline for v6 (hough_ml=30).
#
# Run each step manually after the previous one completes.
#
# Step 1: Submit tracking array job (135 jobs × 15 views = 2025 views)
#   python scripts/submit_kekcc.py --config config/kekcc_v6.yaml
#   Monitor: bjobs -J e07v6
#
# Step 2: After tracking done — merge track chunks
#   python scripts/merge_chunks.py \
#     --input   results/chunks_v6 \
#     --output  results/merged_v6.parquet
#
# Step 3: Submit vertex finding array job (135 jobs)
#   python scripts/submit_vertex_kekcc.py \
#     --chunk-dir  results/chunks_v6 \
#     --vertex-dir results/vertex_chunks_v6 \
#     --walltime   00:30
#   Monitor: bjobs -J e07vertex
#
# Step 4: After vertex finding done — merge vertex files
#   python scripts/merge_chunks.py \
#     --input   results/vertex_chunks_v6 \
#     --pattern "vertex_*.parquet" \
#     --output  results/vertices_v6.parquet
#
# Step 5: Merge vertex slices
#   python scripts/merge_vertices.py \
#     --input  results/vertices_v6.parquet \
#     --output results/vertices_merged_v6.parquet \
#     --min-slices 2 \
#     --min-tracks 5
#
# Step 6: Find intra-view vertex pairs
#   python scripts/find_pairs.py \
#     --input   results/vertices_merged_v6.parquet \
#     --output  results/vertex_pairs_v8.parquet \
#     --d-min-um   90 \
#     --d-max-um  500 \
#     --min-n-primary 5 \
#     --max-dz-mm  0.010
#
# Step 7: Find cross-view vertex pairs
#   python scripts/find_crossview_pairs.py \
#     --vertices results/vertices_merged_v6.parquet \
#     --output   results/vertex_pairs_xview_v2.parquet \
#     --d-min-um   90 \
#     --d-max-um  500 \
#     --max-dz-mm  0.200

set -euo pipefail
echo "See comments above for each step."
echo "Run steps individually after each KEKCC job completes."
