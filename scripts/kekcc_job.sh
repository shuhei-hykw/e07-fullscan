#!/usr/bin/env bash
# LSF array job script for e07fullscan analysis.
# Called by submit_kekcc.sh — do not run directly.
#
# Args: DATA_DIR N_JOBS WORKERS OUT_DIR PROJECT_DIR

set -euo pipefail

DATA_DIR="$1"
N_JOBS="$2"
WORKERS="$3"
OUT_DIR="$4"
PROJECT_DIR="$5"

# LSB_JOBINDEX is 1-based; --chunk-id is 0-based
CHUNK_ID=$((LSB_JOBINDEX - 1))
CHUNK_PAD=$(printf "%04d" "$LSB_JOBINDEX")
OUT_FILE="${OUT_DIR}/chunk_${CHUNK_PAD}.parquet"
LOG_FILE="${PROJECT_DIR}/logs/kekcc/analyze_${CHUNK_PAD}.log"

cd "$PROJECT_DIR"

# Activate conda environment if available
if command -v conda &>/dev/null; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate myenv 2>/dev/null || true
fi

echo "=== chunk ${LSB_JOBINDEX}/${N_JOBS} ===" | tee "$LOG_FILE"
echo "Host    : $(hostname)"          | tee -a "$LOG_FILE"
echo "Start   : $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "Output  : $OUT_FILE"           | tee -a "$LOG_FILE"
echo "---"                            | tee -a "$LOG_FILE"

python -m e07fullscan.analyze \
  "$DATA_DIR" \
  -o "$OUT_FILE" \
  --chunk-id  "$CHUNK_ID" \
  --chunk-total "$N_JOBS" \
  --config "${PROJECT_DIR}/config/default.yaml" \
  -j 1 \
  -v \
  2>> "$LOG_FILE"

echo "---"                            | tee -a "$LOG_FILE"
echo "End     : $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
