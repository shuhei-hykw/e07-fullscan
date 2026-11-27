#!/usr/bin/env bash
# Run union_inputs.py (embedded and --real) and candidate_features.py
# for a two-view sim pair DATASET_A / DATASET_B, each split into NCHUNK
# event chunks run in parallel (separate --out dirs, merged afterwards).
#
#   scripts/run_twoview_chain.sh twoview_v26_nagara80 [NCHUNK]
#   # -> results/sim_eval/<DATASET>_{A,B}{,_real}_*; logs/twoview/
set -euo pipefail
BASE=$1
NCHUNK=${2:-4}
REPO=$(cd "$(dirname "$0")/.." && pwd)
PY=/home/hayakawa/work/.venv/bin/python
IMAGES=$REPO/../e07-g4-hypernuclei/data/images
SIM=$REPO/results/sim_eval
TMP=$SIM/chunks
LOG=$REPO/logs/twoview
mkdir -p "$TMP" "$LOG"
cd "$REPO"

one() {   # one() SET REALFLAG
  local set=$1 real=$2 name=$1${2:+_real}
  local n per pids=()
  n=$(ls -d "$IMAGES/$set"/ev* | wc -l)
  per=$(( (n + NCHUNK - 1) / NCHUNK ))
  for ((k = 0; k < NCHUNK; k++)); do
    nice "$PY" scripts/union_inputs.py "$set" ${real:+--real} \
      --first $((k * per)) --last $(((k + 1) * per)) \
      --out "$TMP/$name.$k" > "$LOG/union_inputs_$name.$k.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  for kind in methodA_production bprime events; do
    local out=$SIM/${name}_$kind.csv first=1
    : > "$out"
    for ((k = 0; k < NCHUNK; k++)); do
      local f=$TMP/$name.$k/${name}_$kind.csv
      [[ -s $f ]] || continue
      if ((first)); then cat "$f" >> "$out"; first=0
      else tail -n +2 "$f" >> "$out"; fi
    done
  done
  touch "$SIM/$name.done"
  nice "$PY" scripts/candidate_features.py "$name" \
    > "$LOG/candidate_features_$name.log" 2>&1
  echo "finished $name"
}

for side in A B; do
  one "${BASE}_$side" "" &
  one "${BASE}_$side" 1 &
done
wait
echo "all done $BASE"
