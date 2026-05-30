#!/usr/bin/env python
"""Thin wrapper to module.clustering._cli_merge_vertices (back-compat)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module.clustering._cli_merge_vertices import main  # noqa: E402
if __name__ == "__main__":
  main()
