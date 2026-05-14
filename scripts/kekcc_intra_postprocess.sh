#!/usr/bin/env bash
# LSF single job: merge intra-view filter slices → annotate → strong selection.
# Run after the e07intra array job completes.
#   $1 SLICES_DIR  (e.g. results/intra_filter_slices)
#   $2 PROJECT_DIR

set -euo pipefail

SLICES_DIR="$1"
PROJECT_DIR="$2"

cd "$PROJECT_DIR"

if command -v conda &>/dev/null; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate myenv 2>/dev/null || true
fi

LOG="${PROJECT_DIR}/logs/kekcc/intra_postprocess.log"
exec > >(tee "$LOG") 2>&1

echo "=== intra post-process: merge + annotate + strong ===" && date

# Merge slices
python - <<'EOF'
import pandas as pd
from pathlib import Path
slices = sorted(Path("results/intra_filter_slices").glob("slice_*.parquet"))
print(f"merging {len(slices)} slices …")
df = pd.concat([pd.read_parquet(s) for s in slices], ignore_index=True)
print(f"  total: {len(df)} pairs")
df.to_parquet("results/vertex_pairs_v6_filtered.parquet", index=False)
print("saved -> vertex_pairs_v6_filtered.parquet")
EOF

# Annotate (connecting track properties)
python scripts/annotate_pairs.py \
  --pairs   results/vertex_pairs_v6_filtered.parquet \
  --output  results/vertex_pairs_v6_ann.parquet

# Strong selection
python - <<'EOF'
import pandas as pd

df = pd.read_parquet("results/vertex_pairs_v6_ann.parquet")
print(f"annotated: {len(df)} pairs")

mask = (
  (df.p_angle_spread >= 30.0) &
  (df.s_angle_spread >= 25.0) &
  (df.p_ntracks >= 8) &
  (df.s_ntracks >= 4) &
  (df.dist_um <= 400.0)
)
strong = df[mask].reset_index(drop=True)
strong.to_parquet("results/vertex_pairs_v6_strong.parquet", index=False)
print(f"strong ({len(strong)} pairs) -> vertex_pairs_v6_strong.parquet")

if "conn_mean_intens" in strong.columns:
  tier_a = strong[strong.conn_mean_intens < 38].reset_index(drop=True)
  tier_a.to_parquet("results/vertex_pairs_v6_tier_a.parquet", index=False)
  print(f"Tier A ({len(tier_a)} pairs) -> vertex_pairs_v6_tier_a.parquet")
EOF

echo "=== done ===" && date
