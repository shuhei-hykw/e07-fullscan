#!/usr/bin/env bash
# Wrapper for module.analyze that captures verbose log for monitor.py.
#
# Usage:
#   scripts/analyze.sh <data_dir> [options]
#
# Options are passed directly to module.analyze.
# stderr (progress lines) is tee'd to analyze.log in the output directory.
#
# Example:
#   scripts/analyze.sh \
#     /gpfs/group/had/sks/E07/tohoku/fullscan/MOD108/PL12/tohoku-v1/AREA00/IMAGE00_AREA00 \
#     -o test_results/chunk_000.parquet \
#     --config config/default.yaml
#
# Then monitor in another tmux window:
#   python scripts/monitor.py \
#     --log analyze.log \
#     --output test_results/chunk_000.parquet \
#     --total 2025

set -euo pipefail

LOG_FILE="analyze.log"

echo "=== E07 fullscan analyze ===" | tee "$LOG_FILE"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
echo "Args: $*" | tee -a "$LOG_FILE"
echo "Log:  $LOG_FILE" | tee -a "$LOG_FILE"
echo "Monitor: python scripts/monitor.py --log $LOG_FILE --output <parquet>"
echo "---" | tee -a "$LOG_FILE"

python -m module.analyze -v "$@" 2>> "$LOG_FILE"

echo "---" | tee -a "$LOG_FILE"
echo "Finished: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_FILE"
