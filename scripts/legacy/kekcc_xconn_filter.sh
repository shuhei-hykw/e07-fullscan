#!/usr/bin/env bash
# LSF single job: cross-view boundary-crossing track filter
# Submitted by: bsub -J e07xconn -q s -n 1 -M 8000 -W 04:00 ...

set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if command -v conda &>/dev/null; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate myenv 2>/dev/null || true
fi

LOG="$PROJECT_DIR/logs/kekcc/xconn_filter.log"
exec > >(tee "$LOG") 2>&1

echo "=== cross-view conn filter ==="
date

python scripts/legacy/filter_xview_pairs.py \
  --pairs   results/vertex_pairs_xview_v6_prefiltered.parquet \
  --chunks  results/chunks_v6 \
  --output  results/vertex_pairs_xview_v6_conn.parquet

echo "=== done ===" && date
