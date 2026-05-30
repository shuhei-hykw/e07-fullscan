#!/usr/bin/env bash
# LSF single job: merge xview conn filter slices.
# Run after the e07xconn array job completes.
#   $1 SLICES_DIR
#   $2 PROJECT_DIR

set -euo pipefail

SLICES_DIR="$1"
PROJECT_DIR="$2"

cd "$PROJECT_DIR"

if command -v conda &>/dev/null; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate myenv 2>/dev/null || true
fi

LOG="${PROJECT_DIR}/logs/kekcc/xconn_postprocess.log"
exec > >(tee "$LOG") 2>&1

echo "=== xview conn post-process: merge ===" && date

python - <<'EOF'
import pandas as pd
from pathlib import Path
slices = sorted(Path("results/xconn_filter_slices").glob("slice_*.parquet"))
print(f"merging {len(slices)} slices …")
df = pd.concat([pd.read_parquet(s) for s in slices], ignore_index=True)
print(f"  total: {len(df)} pairs")
df.to_parquet("results/vertex_pairs_xview_v6_conn.parquet", index=False)
print("saved -> vertex_pairs_xview_v6_conn.parquet")
EOF

echo "=== done ===" && date
