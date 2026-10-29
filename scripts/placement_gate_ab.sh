#!/bin/bash
# AB/BA timing runs of two graphdet_pointcloud.py variants on every event
# of a dataset, for rescore_truth_polylines.py --compare.
#
# usage: scripts/placement_gate_ab.sh DATASET_DIR OUT_DIR "ARGS_A" "ARGS_B"
#   e.g. ... v20_embed_evalA_dz4 results/pointcloud_eval/evalA \
#            "--variant production" "--variant rs --depth-refit 2"
#
# Repetition 1 runs A first on even event index, B first on odd;
# repetition 2 reverses that. Outputs OUT_DIR/r1 and OUT_DIR/r2, run
# serially from the repository root. Stop other CPU jobs first.
set -euo pipefail
[ $# -eq 4 ] || { sed -n 5,7p "$0"; exit 1; }
ds=$1 out=$2 a=$3 b=$4
PY=${PY:-python}
cd "$(dirname "$0")/.."
run() {  # rep, args
  # shellcheck disable=SC2086
  "$PY" scripts/graphdet_pointcloud.py "$ev" $2 --out "$out/r$1"
}
i=0
for ev in "$ds"/ev*/; do
  ev=${ev%/}
  for rep in 1 2; do
    if (( (i + rep) % 2 == 1 )); then
      run "$rep" "$a"; run "$rep" "$b"
    else
      run "$rep" "$b"; run "$rep" "$a"
    fi
  done
  i=$((i + 1))
done
