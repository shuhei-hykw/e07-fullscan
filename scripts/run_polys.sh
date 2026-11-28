#!/usr/bin/env bash
# Run bprime_polys.py on the two-view sets (embedded and real twins).
#   scripts/run_polys.sh   # -> results/sim_eval/polys/, logs/polys_*.log
set -uo pipefail
cd "$(dirname "$0")/.."
PY=/home/hayakawa/work/.venv/bin/python
for n in nagara30 nagara80; do
  for s in A B; do
    for r in "" --real; do
      set=twoview_v26_${n}_$s
      nice $PY scripts/bprime_polys.py $set $r \
        > logs/polys_${set}${r:+_real}.log 2>&1
    done
  done
done
echo "all polys done"
