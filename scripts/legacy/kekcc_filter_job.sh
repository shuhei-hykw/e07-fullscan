#!/usr/bin/env bash
# LSF array job: run a filter script on a pre-split input parquet.
# Inputs are pre-split by chunk-group (see pre-processing) so each job
# loads only its assigned chunks, keeping memory < 2 GB.
#
# Args passed from bsub:
#   $1 FILTER_SCRIPT  (e.g. filter_xview_pairs.py or filter_pairs_by_track.py)
#   $2 INPUT_DIR      (dir containing input_NNNN.parquet slices)
#   $3 CHUNKS_DIR     (e.g. results/chunks_v6)
#   $4 OUTPUT_DIR     (dir that will hold slice_NNNN.parquet results)
#   $5 N_JOBS         (total array size)
#   $6 PROJECT_DIR

set -euo pipefail

FILTER_SCRIPT="$1"
INPUT_DIR="$2"
CHUNKS_DIR="$3"
OUTPUT_DIR="$4"
N_JOBS="$5"
PROJECT_DIR="$6"

IDX=$(printf '%04d' "$LSB_JOBINDEX")
INPUT_FILE="${INPUT_DIR}/input_${IDX}.parquet"
SLICE_OUT="${OUTPUT_DIR}/slice_${IDX}.parquet"
LOG="${PROJECT_DIR}/logs/kekcc/filter_${IDX}.log"

cd "$PROJECT_DIR"

if command -v conda &>/dev/null; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate myenv 2>/dev/null || true
fi

exec > >(tee "$LOG") 2>&1
echo "=== job ${LSB_JOBINDEX}/${N_JOBS} ==="
date

python "scripts/legacy/${FILTER_SCRIPT}" \
  --pairs   "${INPUT_FILE}" \
  --chunks  "${CHUNKS_DIR}" \
  --output  "${SLICE_OUT}"

echo "=== done ===" && date
