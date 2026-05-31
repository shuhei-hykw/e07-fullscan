#!/usr/bin/env python3
"""Deprecated entry point - use `python scripts/monitor.py --pipeline`.

The pipeline-overview logic moved to module/pipeline_status.py. This thin
wrapper delegates for back-compat and prints a deprecation note.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from module.pipeline_status import main  # noqa: E402

DEPRECATION = "[deprecated] use: python scripts/monitor.py --pipeline"

if __name__ == "__main__":
  print(DEPRECATION, file=sys.stderr)
  if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
    print(__doc__)
    sys.exit(0)
  main()
