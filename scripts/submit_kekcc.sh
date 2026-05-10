#!/usr/bin/env bash
# Submit e07fullscan analysis as an LSF array job on KEKCC.
#
# Usage:
#   scripts/submit_kekcc.sh [options]
#
# Options:
#   -d DATA_DIR     Input data directory (required)
#   -n N_JOBS       Number of array jobs (default: 25)
#   -j WORKERS      Worker processes per node (default: 4)
#   -q QUEUE        LSF queue name (default: s)
#   -W WALLTIME     Wall time HH:MM (default: 02:00)
#   -M MEM_MB       Memory limit per job in MB (default: 8192)
#   -o OUT_DIR      Output directory (default: test_results)
#
# Example:
#   scripts/submit_kekcc.sh \
#     -d /gpfs/group/had/sks/E07/tohoku/fullscan/MOD108/PL12/tohoku-v1/AREA00/IMAGE00_AREA00 \
#     -n 25 -j 4 -q s

set -euo pipefail

# ---------- defaults ----------
DATA_DIR=""
N_JOBS=25
WORKERS=4
QUEUE="s"
WALLTIME="02:00"
MEM_MB=8192
OUT_DIR="test_results"

# ---------- parse args ----------
while getopts "d:n:j:q:W:M:o:" opt; do
  case $opt in
    d) DATA_DIR="$OPTARG" ;;
    n) N_JOBS="$OPTARG" ;;
    j) WORKERS="$OPTARG" ;;
    q) QUEUE="$OPTARG" ;;
    W) WALLTIME="$OPTARG" ;;
    M) MEM_MB="$OPTARG" ;;
    o) OUT_DIR="$OPTARG" ;;
    *) echo "Unknown option -$OPTARG"; exit 1 ;;
  esac
done

if [[ -z "$DATA_DIR" ]]; then
  echo "ERROR: -d DATA_DIR is required."
  exit 1
fi

# ---------- prepare ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs/kekcc"
mkdir -p "$LOG_DIR" "$OUT_DIR"

echo "=== E07 KEKCC job submission ==="
echo "  Data     : $DATA_DIR"
echo "  Jobs     : $N_JOBS"
echo "  Workers  : $WORKERS per job"
echo "  Queue    : $QUEUE"
echo "  Walltime : $WALLTIME"
echo "  Memory   : ${MEM_MB} MB"
echo "  Output   : $OUT_DIR"
echo "  Logs     : $LOG_DIR"
echo ""

# ---------- submit array job ----------
JOB_ID=$(bsub \
  -J "e07analyze[1-${N_JOBS}]" \
  -q "$QUEUE" \
  -n "$WORKERS" \
  -W "$WALLTIME" \
  -M "$MEM_MB" \
  -o "$LOG_DIR/job_%I.log" \
  -e "$LOG_DIR/job_%I.err" \
  "$SCRIPT_DIR/kekcc_job.sh" \
    "$DATA_DIR" "$N_JOBS" "$WORKERS" "$OUT_DIR" "$PROJECT_DIR" \
  | grep -oP '(?<=Job <)\d+')

echo "Submitted array job: $JOB_ID"
echo ""
echo "Monitor:"
echo "  bjobs -J e07analyze"
echo "  bjobs $JOB_ID"
echo ""
echo "After completion, merge results:"
echo "  python scripts/merge_chunks.py --input $OUT_DIR --output $OUT_DIR/merged.parquet"
