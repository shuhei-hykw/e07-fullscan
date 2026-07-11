#!/usr/bin/env python3
"""E07 full-scan operations entry point.

Usage:
  python run.py <command> [args...]
  python run.py --help

Commands:
  track            local full-scan track analysis
  merge-tracks     merge chunk_*.parquet
  vertices         find vertices from tracks
  merge-vertices   merge per-slice vertices + crops
  crops            crop vertices for inspection
  review           web review of vertex crops
  map              spatial vertex distribution map
  click            click ground-truth vertices
  submit-tracking  submit tracking LSF array (KEKCC)
  submit-vertices  submit vertex LSF array (KEKCC)
  matlab-export    export tile as 3-D hit list (.mat) for MATLAB
  view             vertex review/3D viewer server
  monitor          live job monitor  (add --loop N for polling)
  status           pipeline overview

Diagnostics: python -m module.pipeline.diag_<name>
  names: step5_compat, lowsp_diag, lowsp_spread_radius, diag_bg_cost_spread
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

COMMANDS: dict[str, str] = {
  "track":           "module.pipeline.analyze_cli",
  "view":            "module.server",
  "merge-tracks":    "module.pipeline.cli_merge_chunks",
  "vertices":        "module.pipeline.cli_find_vertices",
  "merge-vertices":  "module.pipeline.cli_merge_vertices",
  "crops":           "module.pipeline.cli_crop_vertices",
  "review":          "module.pipeline.cli_review_crops",
  "map":             "module.pipeline.cli_vertex_map",
  "click":           "module.pipeline.cli_click_vertex",
  "submit-tracking": "module.pipeline.cli_submit_kekcc",
  "submit-vertices": "module.pipeline.cli_submit_vertex_kekcc",
  "matlab-export":   "module.matlab_export",
  "monitor":         "module.job_monitor",
  "status":          "module.pipeline_status",
}


def _usage() -> None:
  print(__doc__)


def main() -> int:
  if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
    _usage()
    return 0
  cmd = sys.argv[1]
  rest = sys.argv[2:]
  if cmd not in COMMANDS:
    print(f"unknown command: {cmd}\n", file=sys.stderr)
    _usage()
    return 2
  argv = [sys.executable, "-m", COMMANDS[cmd], *rest]
  return subprocess.run(argv, cwd=str(ROOT)).returncode


if __name__ == "__main__":
  raise SystemExit(main())
