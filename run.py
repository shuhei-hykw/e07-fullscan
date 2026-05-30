#!/usr/bin/env python3
"""E07 full-scan operations entry point.

Single command surface for the everyday pipeline. Each subcommand delegates to
the existing implementation (a script under scripts/ or a module entry point)
so behavior is unchanged — this is just one place to discover and launch them.

Usage:
  python run.py <command> [args...]
  python run.py <command> --help
  python run.py --help

Commands:
  track            local full-scan track analysis   (-> python -m module.analyze)
  merge-tracks     merge chunk_*.parquet            (-> scripts/merge_chunks.py)
  vertices         find vertices from tracks        (-> scripts/find_vertices.py)
  merge-vertices   merge per-slice vertices + crops (-> scripts/merge_vertices.py)
  crops            crop vertices for inspection     (-> scripts/crop_vertices.py)
  review           web review of vertex crops       (-> scripts/review_crops.py)
  map              spatial vertex distribution map  (-> scripts/vertex_map.py)
  click            click ground-truth vertices      (-> scripts/click_vertex.py)
  submit-tracking  submit tracking LSF array (KEKCC) (-> scripts/submit_kekcc.py)
  submit-vertices  submit vertex LSF array (KEKCC)   (-> scripts/submit_vertex_kekcc.py)
  view             vertex review/3D viewer server    (-> python -m module.server)

Monitoring stays separate: `python scripts/monitor.py [--loop N]`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"

# command -> argv prefix (relative to repo root). A leading "-m" entry runs a
# module; otherwise the entry is a script path executed with the interpreter.
_SCRIPT = "script"
_MODULE = "module"
COMMANDS: dict[str, tuple[str, str]] = {
  "track":           (_MODULE, "module.analyze"),
  "view":            (_MODULE, "module.server"),
  "merge-tracks":    (_SCRIPT, "merge_chunks.py"),
  "vertices":        (_SCRIPT, "find_vertices.py"),
  "merge-vertices":  (_SCRIPT, "merge_vertices.py"),
  "crops":           (_SCRIPT, "crop_vertices.py"),
  "review":          (_SCRIPT, "review_crops.py"),
  "map":             (_SCRIPT, "vertex_map.py"),
  "click":           (_SCRIPT, "click_vertex.py"),
  "submit-tracking": (_SCRIPT, "submit_kekcc.py"),
  "submit-vertices": (_SCRIPT, "submit_vertex_kekcc.py"),
}


def _usage() -> None:
  print(__doc__)
  print("Available commands:")
  for name in COMMANDS:
    print(f"  {name}")


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
  kind, target = COMMANDS[cmd]
  if kind == _MODULE:
    argv = [sys.executable, "-m", target, *rest]
  else:
    argv = [sys.executable, str(SCRIPTS / target), *rest]
  # run from repo root so PYTHONPATH=. style imports and relative paths hold
  return subprocess.run(argv, cwd=str(ROOT)).returncode


if __name__ == "__main__":
  raise SystemExit(main())
