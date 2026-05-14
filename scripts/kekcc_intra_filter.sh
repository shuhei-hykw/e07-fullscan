#!/usr/bin/env bash
# LSF single job: intra-view conn filter → annotate → strong selection
# Submitted by: bsub -J e07intra -q s -n 1 -M 8000 -W 01:30 ...

set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if command -v conda &>/dev/null; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate myenv 2>/dev/null || true
fi

LOG="$PROJECT_DIR/logs/kekcc/intra_filter.log"
exec > >(tee "$LOG") 2>&1

echo "=== intra-view conn filter ==="
date

python scripts/filter_pairs_by_track.py \
  --pairs   results/vertex_pairs_v6.parquet \
  --chunks  results/chunks_v6 \
  --output  results/vertex_pairs_v6_filtered.parquet \
  --min-n-primary 10

echo "--- annotate pairs ---"
python scripts/annotate_pairs.py \
  --pairs   results/vertex_pairs_v6_filtered.parquet \
  --chunks  results/chunks_v6 \
  --output  results/vertex_pairs_v6_ann.parquet

echo "--- strong candidate selection ---"
python - <<'EOF'
import pandas as pd

df = pd.read_parquet("results/vertex_pairs_v6_ann.parquet")
print(f"input: {len(df)} pairs")

mask = (
  (df.p_angle_spread >= 30.0) &
  (df.s_angle_spread >= 25.0) &
  (df.p_ntracks >= 8) &
  (df.s_ntracks >= 4) &
  (df.dist_um <= 400.0)
)
strong = df[mask].reset_index(drop=True)
strong.to_parquet("results/vertex_pairs_v6_strong.parquet", index=False)
print(f"strong: {len(strong)} pairs")

# Tier A: even stricter
if "conn_mean_intens" in strong.columns:
  tier_a = strong[strong.conn_mean_intens < 38].reset_index(drop=True)
  tier_a.to_parquet("results/vertex_pairs_v6_tier_a.parquet", index=False)
  print(f"Tier A (intens<38): {len(tier_a)} pairs")
EOF

echo "=== done ===" && date
