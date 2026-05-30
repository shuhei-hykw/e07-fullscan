#!/usr/bin/env python
"""Submit vertex finding as an LSF array job on KEKCC.

Usage:
  python scripts/submit_vertex_kekcc.py
  python scripts/submit_vertex_kekcc.py --dry-run
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Submit KEKCC vertex LSF job")
    ap.add_argument("--chunk-dir",  type=Path, default=Path("results"),
                    help="Directory containing chunk_NNNN.parquet")
    ap.add_argument("--vertex-dir", type=Path, default=Path("results/vertex_chunks"),
                    help="Output directory for vertex_NNNN.parquet")
    ap.add_argument("--n-jobs",   type=int, default=None,
                    help="Number of array jobs (default: auto from chunk count)")
    ap.add_argument("--queue",    default="s")
    ap.add_argument("--mem-mb",   type=int, default=8000)
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

    project_dir = Path(__file__).resolve().parents[2]
    log_dir = project_dir / "logs" / "kekcc"
    log_dir.mkdir(parents=True, exist_ok=True)

    print("=== E07 KEKCC vertex job submission ===")
    print(f"  Chunk dir  : {args.chunk_dir}  ({len(chunks)} chunks)")
    print(f"  Vertex dir : {args.vertex_dir}")
    print(f"  Jobs       : {n_jobs}")
    print(f"  Queue      : {args.queue}")
    print(f"  Memory     : {args.mem_mb} MB")
    print(f"  Walltime   : {args.walltime}")
    print()

    cmd = [
        "bsub",
        "-J", f"e07vertex[1-{n_jobs}]",
        "-q", args.queue,
        "-n", "1",
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
        print("  " + " \\\n    ".join(cmd))
        return

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        sys.exit(result.returncode)

    m = re.search(r"Job <(\d+)>", result.stdout)
    job_id = m.group(1) if m else "?"
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
