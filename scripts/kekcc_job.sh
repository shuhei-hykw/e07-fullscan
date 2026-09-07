#!/usr/bin/env bash
# LSF array job script for module analysis.
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
# Never silently overwrite: results/ still holds the 2026-05-14 run at
# hough_mg=5, whose chunk_0001..0135 names would collide with the first
# 135 jobs of a 2025-job array and leave the directory half old.
if [ -e "$OUT_FILE" ]; then
  echo "refusing to overwrite $OUT_FILE" >&2
  exit 1
fi
LOG_FILE="${PROJECT_DIR}/logs/kekcc/analyze_${CHUNK_PAD}.log"

cd "$PROJECT_DIR"

# The project environment is conda `myenv`; the default python3.12 on
# kekcc is missing cv2/scipy/sklearn. Activate it if conda is on PATH,
# and fall back to the interpreter path directly if it is not -- a
# batch node without conda would otherwise run the wrong python and
# fail 2025 times.
PY=python
if command -v conda &>/dev/null; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate myenv 2>/dev/null || true
fi
if ! "$PY" -c "import cv2" 2>/dev/null; then
  PY="$HOME/.conda/envs/myenv/bin/python"
fi
"$PY" -c "import cv2, scipy, numpy" || {
  echo "no usable python (need cv2/scipy/numpy)" >&2; exit 1; }

echo "=== chunk ${LSB_JOBINDEX}/${N_JOBS} ===" | tee "$LOG_FILE"
echo "Host    : $(hostname)"          | tee -a "$LOG_FILE"
echo "Start   : $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "Output  : $OUT_FILE"           | tee -a "$LOG_FILE"
echo "---"                            | tee -a "$LOG_FILE"

"$PY" -m module.pipeline \
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
