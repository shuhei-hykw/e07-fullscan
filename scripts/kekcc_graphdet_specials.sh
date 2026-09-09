#!/usr/bin/env bash
# LSF array job: graph detector on one specials event per index.
# Args: EVENT_LIST(comma-separated) OUT_DIR PROJECT_DIR

set -euo pipefail

EVENT_LIST="$1"
OUT_DIR="$2"
PROJECT_DIR="$3"

IFS=',' read -r -a EVENTS <<< "$EVENT_LIST"
EVENT="${EVENTS[$((LSB_JOBINDEX - 1))]}"

cd "$PROJECT_DIR"

# The project env is conda `myenv`; fall back to its interpreter if the
# batch node has no conda (see kekcc_job.sh).
PY=python
if command -v conda &>/dev/null; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate myenv 2>/dev/null || true
fi
if ! "$PY" -c "import cv2" 2>/dev/null; then
  PY="$HOME/.conda/envs/myenv/bin/python"
fi
"$PY" -c "import cv2, scipy, sklearn" || {
  echo "no usable python (need cv2/scipy/sklearn)" >&2; exit 1; }

if [ -e "${OUT_DIR}/${EVENT}.json" ]; then
  echo "refusing to overwrite ${OUT_DIR}/${EVENT}.json" >&2
  exit 1
fi

echo "=== graphdet specials: ${EVENT} (index ${LSB_JOBINDEX}) ==="
echo "Host  : $(hostname)"
echo "Start : $(date '+%Y-%m-%d %H:%M:%S')"

"$PY" -u scripts/graphdet_specials.py --event "$EVENT" --out "$OUT_DIR"

echo "End   : $(date '+%Y-%m-%d %H:%M:%S')"
