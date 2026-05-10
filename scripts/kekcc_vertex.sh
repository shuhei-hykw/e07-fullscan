#!/usr/bin/env bash
# LSF array job script for vertex finding.
# Args: CHUNK_DIR VERTEX_DIR N_JOBS PROJECT_DIR

set -euo pipefail

CHUNK_DIR="$1"
VERTEX_DIR="$2"
N_JOBS="$3"
PROJECT_DIR="$4"

CHUNK_PAD=$(printf "%04d" "$LSB_JOBINDEX")
IN_FILE="${CHUNK_DIR}/chunk_${CHUNK_PAD}.parquet"
OUT_FILE="${VERTEX_DIR}/vertex_${CHUNK_PAD}.parquet"
LOG_FILE="${PROJECT_DIR}/logs/kekcc/vertex_${CHUNK_PAD}.log"

cd "$PROJECT_DIR"

if command -v conda &>/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate myenv 2>/dev/null || true
fi

echo "=== vertex ${LSB_JOBINDEX}/${N_JOBS} ===" | tee "$LOG_FILE"
echo "Input : $IN_FILE"  | tee -a "$LOG_FILE"
echo "Output: $OUT_FILE" | tee -a "$LOG_FILE"
echo "Start : $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "---" | tee -a "$LOG_FILE"

python scripts/find_vertices.py \
    --input  "$IN_FILE" \
    --output "$OUT_FILE" \
    --min-tracks     3 \
    --min-tracks-out 3 \
    --min-intens    10.0 \
    --min-len        50.0 \
    --max-impact     30.0 \
    --max-ep        150.0 \
    --max-ep-frac     0.5 \
    --eps            25.0 \
    --beam-angle-cut  15.0 \
    --min-angle-spread 20.0 \
    2>> "$LOG_FILE"

echo "---" | tee -a "$LOG_FILE"
echo "End   : $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
