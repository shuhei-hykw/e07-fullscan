from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Track:
    """A detected track segment in stage coordinates."""
    x1: float        # stage x of start point
    y1: float        # stage y of start point
    x2: float        # stage x of end point
    y2: float        # stage y of end point
    z: float         # stage z of the slice
    px1: int         # pixel x of start point (for visualization)
    py1: int         # pixel y of start point
    px2: int         # pixel x of end point
    py2: int         # pixel y of end point
    length_px: float # Hough segment length in pixels
    angle_deg: float # line angle 0-180 degrees
    view_id: str     # source JSON path
