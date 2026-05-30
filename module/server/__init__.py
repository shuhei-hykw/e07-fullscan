"""
Lightweight Flask-based web viewer for SPNG image stacks.

Install the extra dependency before use:
  pip install module[server]

Start the server:
  python -m module.server /path/to/data/root
"""

from module.server.app import create_app, run

__all__ = ["create_app", "run"]
