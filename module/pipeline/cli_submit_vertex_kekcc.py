#!/usr/bin/env python
"""Submit vertex finding as an LSF array job on KEKCC.

Usage:
  python scripts/submit_vertex_kekcc.py
  python scripts/submit_vertex_kekcc.py --dry-run
"""
from __future__ import annotations

import argparse
import getpass
import re
import subprocess
import sys
from pathlib import Path

from module.pipeline import lsf_queue

# Measured on a real chunk, 2026-09-09: 22 s wall, 705 MB peak for one
# view's 634k tracks under the production cuts.
_CPU_MIN_PER_CHUNK = 0.5
_SAFETY = 4.0
_AUTO = "auto"


def main() -> None:
    ap = argparse.ArgumentParser(description="Submit KEKCC vertex LSF job")
    ap.add_argument("--chunk-dir",  type=Path, default=Path("results"),
                    help="Directory containing chunk_NNNN.parquet")
    ap.add_argument("--vertex-dir", type=Path,
                    default=Path("results/vertex_chunks"),
                    help="Output directory for vertex_NNNN.parquet")
    ap.add_argument("--n-jobs",   type=int, default=None,
                    help="Array size (default: one job per chunk)")
    ap.add_argument("--queue",    default=_AUTO,
                    help='"auto" picks the least-loaded usable queue')
    ap.add_argument("--array",    default=None, metavar="LO-HI",
                    help="Submit only these array indices (e.g. 1-20)")
    ap.add_argument("--mem-mb",   type=int, default=4000)
    # Vertex finding is single-threaded, but asking for one slot rules
    # out queue p, whose TASKLIMIT starts at 2 and which is by far the
    # least contended. Two slots costs a spare slot and buys 30x the
    # concurrency (120 jobs at once against 4).
    ap.add_argument("--n-cores",  type=int, default=2)
    ap.add_argument("--walltime", default="00:30")
    ap.add_argument("--dry-run",  action="store_true")
    args = ap.parse_args()

    chunks = sorted(args.chunk_dir.glob("chunk_*.parquet"))
    if not chunks:
        print(f"ERROR: no chunk_*.parquet in {args.chunk_dir}",
              file=sys.stderr)
        sys.exit(1)

    n_jobs = args.n_jobs or len(chunks)
    args.vertex_dir.mkdir(parents=True, exist_ok=True)
    array = args.array or f"1-{n_jobs}"
    lo, _, hi = array.partition("-")
    lo, hi = int(lo), int(hi or lo)
    batches = lsf_queue.split_array(lo, hi, lsf_queue.max_array_size())

    queue = args.queue
    if queue == _AUTO:
        run_min = int(args.walltime.split(":")[0]) * 60 + int(
            args.walltime.split(":")[1])
        ranked = lsf_queue.rank(args.n_cores, args.mem_mb,
                                _CPU_MIN_PER_CHUNK * _SAFETY, run_min,
                                user=getpass.getuser())
        if not ranked:
            print("ERROR: no queue can hold this job", file=sys.stderr)
            sys.exit(1)
        print("Queue selection (best first):")
        print(lsf_queue.describe(ranked))
        queue = ranked[0]["name"]
        print(f"  -> {queue}\n")

    project_dir = Path(__file__).resolve().parents[2]
    log_dir = project_dir / "logs" / "kekcc"
    log_dir.mkdir(parents=True, exist_ok=True)

    print("=== E07 KEKCC vertex job submission ===")
    print(f"  Chunk dir  : {args.chunk_dir}  ({len(chunks)} chunks)")
    print(f"  Vertex dir : {args.vertex_dir}")
    print(f"  Jobs       : {array}  ({hi - lo + 1} jobs in "
          f"{len(batches)} array(s))")
    print(f"  Queue      : {queue}")
    print(f"  Memory     : {args.mem_mb} MB")
    print(f"  Walltime   : {args.walltime}")
    print()

    def build(lo_i: int, hi_i: int) -> list[str]:
        return [
        "bsub",
        "-J", f"e07vertex[{lo_i}-{hi_i}]",
        "-q", queue,
        "-n", str(args.n_cores),
        "-M", str(args.mem_mb),
        "-W", args.walltime,
        "-o", str(log_dir / "vertex_%I.log"),
        "-e", str(log_dir / "vertex_%I.err"),
        str(project_dir / "scripts" / "kekcc_vertex.sh"),
        str(args.chunk_dir),
        str(args.vertex_dir),
        str(n_jobs),
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
    print(f"  bjobs -J e07vertex")
    print()
    print("After completion:")
    print(f"  python scripts/merge_chunks.py "
          f"--input {args.vertex_dir} "
          f"--pattern 'vertex_*.parquet' "
          f"--output results/vertices.parquet")


if __name__ == "__main__":
    main()
