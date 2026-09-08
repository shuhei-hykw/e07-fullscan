#!/usr/bin/env python
"""Submit module analysis as an LSF array job on KEKCC.

Usage:
  python scripts/submit_kekcc.py
  python scripts/submit_kekcc.py --config config/kekcc.yaml
  python scripts/submit_kekcc.py --dry-run   # print bsub command only
  python scripts/submit_kekcc.py --array 1-20   # pilot, first 20 views

`queue: auto` in the config picks the queue that can start the most
jobs right now (see module.pipeline.lsf_queue). Which queue that is
changes by the hour, so it is worth asking rather than hard-coding.

`--array` restricts which array indices are submitted WITHOUT changing
--chunk-total, so a pilot covers a real slice of the same partition
the full run will use and its output is not thrown away.
"""
from __future__ import annotations

import argparse
import getpass
import re
import subprocess
import sys
from pathlib import Path

import yaml

from module.pipeline import lsf_queue

# Per-view cost measured on a real E07 tile, 2026-09-08: 128 s wall,
# 277 s CPU, 1.55 GB. Used to reject queues whose limits cannot hold
# one job, with room for denser views.
_CPU_MIN_PER_VIEW = 277 / 60.0
_SAFETY = 3.0
_AUTO = "auto"


def _load(cfg_path: Path) -> dict:
    return yaml.safe_load(cfg_path.read_text()) or {}


def main() -> None:
    ap = argparse.ArgumentParser(description="Submit KEKCC LSF array job")
    ap.add_argument("--config", type=Path,
                    default=Path("config/kekcc.yaml"),
                    help="Job config YAML (default: config/kekcc.yaml)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print bsub command without submitting")
    ap.add_argument("--array", default=None, metavar="LO-HI",
                    help="Submit only these array indices (e.g. 1-20); "
                         "--chunk-total is unchanged")
    args = ap.parse_args()

    if not args.config.exists():
        print(f"ERROR: config not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    cfg      = _load(args.config)
    job      = cfg.get("job", {})
    data     = cfg.get("data", {})
    analysis = cfg.get("analysis", {})

    name     = job.get("name",     "e07analyze")
    queue    = job.get("queue",    "s")
    n_cores  = int(job.get("n_cores",  2))
    mem_mb   = int(job.get("mem_mb",   4000))
    walltime = str(job.get("walltime", "02:00"))
    n_jobs   = int(job.get("n_jobs",   25))

    input_dir  = data.get("input", "")
    output_dir = data.get("output_dir", "test_results")
    total      = int(data.get("total_views", 2025))

    ana_cfg  = analysis.get("config",  "config/default.yaml")
    workers  = int(analysis.get("workers", 1))

    project_dir = Path(__file__).resolve().parents[2]
    log_dir     = project_dir / "logs" / "kekcc"
    log_dir.mkdir(parents=True, exist_ok=True)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    views_per_job = (total + n_jobs - 1) // n_jobs
    array = args.array or f"1-{n_jobs}"
    lo, _, hi = array.partition("-")
    lo, hi = int(lo), int(hi or lo)
    batches = lsf_queue.split_array(lo, hi, lsf_queue.max_array_size())
    n_submitted = hi - lo + 1

    if queue == _AUTO:
        cpu_min = _CPU_MIN_PER_VIEW * views_per_job * _SAFETY
        run_min = int(walltime.split(":")[0]) * 60 + int(
            walltime.split(":")[1])
        ranked = lsf_queue.rank(n_cores, mem_mb, cpu_min, run_min,
                                user=getpass.getuser())
        if not ranked:
            print("ERROR: no queue can hold this job", file=sys.stderr)
            sys.exit(1)
        print("Queue selection (best first):")
        print(lsf_queue.describe(ranked))
        queue = ranked[0]["name"]
        print(f"  -> {queue}\n")

    print("=== E07 KEKCC job submission ===")
    print(f"  Config     : {args.config}")
    print(f"  Job name   : {name}[{array}]  ({n_submitted} jobs "
          f"in {len(batches)} array(s))")
    print(f"  Queue      : {queue}")
    print(f"  Cores/job  : {n_cores}")
    print(f"  Memory     : {mem_mb} MB")
    print(f"  Walltime   : {walltime}")
    print(f"  Jobs       : {n_jobs}  (~{views_per_job} views/job)")
    print(f"  Input      : {input_dir}")
    print(f"  Output dir : {output_dir}")
    print(f"  Log dir    : {log_dir}")
    print()

    def build(lo_i: int, hi_i: int) -> list[str]:
        return [
        "bsub",
        "-J", f"{name}[{lo_i}-{hi_i}]",
        "-q", queue,
        "-n", str(n_cores),
        "-M", str(mem_mb),
        "-W", walltime,
        "-o", str(log_dir / "job_%I.log"),
        "-e", str(log_dir / "job_%I.err"),
        str(project_dir / "scripts" / "kekcc_job.sh"),
        input_dir,
        str(n_jobs),
        str(workers),
        output_dir,
        str(project_dir),
        ]

    if args.dry_run:
        print("bsub command (dry-run):")
        print("  " + " \\\n    ".join(build(*batches[0])))
        if len(batches) > 1:
            print(f"  ... and {len(batches) - 1} more array(s): "
                  + ", ".join(f"{a}-{b}" for a, b in batches[1:]))
        return

    for lo_i, hi_i in batches:
        result = subprocess.run(build(lo_i, hi_i), capture_output=True,
                                text=True)
        print(result.stdout.strip())
        if result.returncode != 0:
            print(result.stderr.strip(), file=sys.stderr)
            sys.exit(result.returncode)

    print()
    print("Monitor:")
    print(f"  bjobs -J {name}")
    print(f"  python scripts/monitor.py --job-name {name} "
          f"--log-dir {log_dir} --out-dir {output_dir} --total {total}")
    print()
    print("After completion:")
    print(f"  python scripts/merge_chunks.py "
          f"--input {output_dir} --output {output_dir}/merged.parquet")


if __name__ == "__main__":
    main()
