#!/usr/bin/env python3
"""Deprecated entry point - use `python scripts/monitor.py --pipeline`.

The pipeline-overview logic moved to module/pipeline_status.py. This thin
wrapper delegates for back-compat and prints a deprecation note.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from module.pipeline_status import main  # noqa: E402

if __name__ == "__main__":
  print("[deprecated] use: python scripts/monitor.py --pipeline",
        file=sys.stderr)
  main()
