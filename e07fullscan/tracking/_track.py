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
    # properties from the raw image (default 0 when not measured)
    n_grains:    int   = 0    # grain blobs overlapping the segment
    width_px:    float = 0.0  # transverse spread of grains (px)
    mean_intens: float = 0.0  # mean fog-removed intensity along track
    px_scale_um: float = 0.0  # μm per pixel (0 = unknown)
    view_x_mm:   float = 0.0  # stage x of this FOV (mm)
    view_y_mm:   float = 0.0  # stage y of this FOV (mm)
