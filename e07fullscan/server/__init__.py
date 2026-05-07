"""
Lightweight Flask-based web viewer for SPNG image stacks.

Install the extra dependency before use:
    pip install e07fullscan[server]

Start the server:
    python -m e07fullscan.server /path/to/data/root
"""

from e07fullscan.server.app import create_app, run

__all__ = ["create_app", "run"]
