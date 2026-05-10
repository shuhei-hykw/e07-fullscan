#!/usr/bin/env python
"""Submit e07fullscan analysis as an LSF array job on KEKCC.

Usage:
  python scripts/submit_kekcc.py
  python scripts/submit_kekcc.py --config config/kekcc.yaml
  python scripts/submit_kekcc.py --dry-run   # print bsub command only
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml


def _load(cfg_path: Path) -> dict:
    return yaml.safe_load(cfg_path.read_text()) or {}


def main() -> None:
    ap = argparse.ArgumentParser(description="Submit KEKCC LSF array job")
    ap.add_argument("--config", type=Path,
                    default=Path("config/kekcc.yaml"),
                    help="Job config YAML (default: config/kekcc.yaml)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print bsub command without submitting")
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

    project_dir = Path(__file__).resolve().parents[1]
    log_dir     = project_dir / "logs" / "kekcc"
    log_dir.mkdir(parents=True, exist_ok=True)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    views_per_job = (total + n_jobs - 1) // n_jobs

    print("=== E07 KEKCC job submission ===")
    print(f"  Config     : {args.config}")
    print(f"  Job name   : {name}[1-{n_jobs}]")
    print(f"  Queue      : {queue}")
    print(f"  Cores/job  : {n_cores}")
    print(f"  Memory     : {mem_mb} MB")
    print(f"  Walltime   : {walltime}")
    print(f"  Jobs       : {n_jobs}  (~{views_per_job} views/job)")
    print(f"  Input      : {input_dir}")
    print(f"  Output dir : {output_dir}")
    print(f"  Log dir    : {log_dir}")
    print()

    cmd = [
        "bsub",
        "-J", f"{name}[1-{n_jobs}]",
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
        print("  " + " \\\n    ".join(cmd))
        return

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        sys.exit(result.returncode)

    # extract job ID from "Job <NNN> is submitted..."
    m = re.search(r"Job <(\d+)>", result.stdout)
    job_id = m.group(1) if m else "?"

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
