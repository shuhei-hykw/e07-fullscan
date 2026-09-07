"""Tunable constants of the graph detector, in one place.

The MATLAB originals were tuned on a simulation that samples a track
every ~3 px. The real E07 export samples every 30 px
(``matlab_export._GRID_CELL_PX``), and at that spacing several of
these constants span less than a single gap between hits, so the step
they gate never fires. Collecting them here is what makes that
testable: ``scripts/scan_sampling.py`` re-thins the same simulation at
other block sizes, so the truth stays intact while the spacing
changes.

The split below is the whole point of the file. A **length scale** is
a distance measured ALONG a track or between neighbouring hits, and it
has to grow with the hit spacing. A **transverse tolerance** is a
distance measured ACROSS a track -- track width plus measurement error
-- and it does not: the E07 export skeletonises each component before
sampling, so its hits sit on the centreline however coarse the grid
is. Scaling the two together is the mistake this separation exists to
prevent.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

# distfun1.m scales the slice axis so that one z step is comparable to
# an x/y pixel: the simulation was made with 3 um slices at 0.29 um/px.
MATLAB_Z_SCALE = 3.0 / 0.29
# E07 full-scan data is 1.5 um/slice, so the MATLAB value is twice too
# large there -- z distances come out doubled.
E07_Z_SCALE = 1.5 / 0.29

# Hit spacing the MATLAB constants were tuned at (mabiki block 3).
MATLAB_SPACING_PX = 3.0
# What matlab_export.export_hits_grid currently produces.
E07_SPACING_PX = 30.0


@dataclass(frozen=True)
class DetectorConfig:
  """Everything the three stages measure a distance against."""

  # -- geometry of the data ------------------------------------------
  z_scale: float = MATLAB_Z_SCALE
  spacing_px: float = MATLAB_SPACING_PX

  # -- transverse tolerances (track width + measurement error) -------
  # Straightness when cutting the spanning tree, and when growing a
  # component onto nearby hits (MATLAB calls both TH).
  th_split: float = 2.0
  th_grow: float = 1.5
  # isaline3: residual still accepted as "these two segments are one
  # straight line".
  join_max_residual: float = 2.0
  # isaline3a: summed sideways kink at a junction.
  join_max_kink: float = 5.0
  # resamplingpoly: how far off a polyline a hit may be and still be
  # claimed by it.
  resample_th: float = 2.0
  # detectbunki: how far off a polyline a hit may be and still count
  # as touching it. The tightest tolerance in the whole pipeline.
  attach_max_dist: float = 1.5

  # -- length scales (scale with hit spacing) ------------------------
  # How far past its own extent a component looks for more hits.
  grow_margin: float = 20.0
  # Endpoint refinement: how far an endpoint may slide, in what steps,
  # and the step below which refining stops.
  refine_dl: float = 20.0
  refine_dl_step: float = 5.0
  refine_dl_min: float = 2.0
  # isaline5: two single-hit components this close are one track.
  single_point_max_dist: float = 20.0
  # Half-widths of the box searched for an endpoint to continue a
  # track into. z is in slices, and a slice is ~10 px, hence far
  # smaller.
  neighbour_xy: float = 50.0
  neighbour_z: float = 5.0
  # isaline3a: how far two polylines may overlap and still be joined.
  join_max_overlap: float = 5.0
  # A polyline shorter than this has a poorly determined direction, so
  # its angle is weak evidence and the join test is loosened.
  join_short_poly: float = 20.0
  # detectbunki: a hit is "at an end" within this of one, and may
  # reach this much further past it.
  end_margin: float = 5.0
  end_reach: float = 25.0
  # Shared-hit centroids closer than this describe the same vertex.
  vertex_merge: float = 10.0

  def for_spacing(self, spacing_px: float) -> "DetectorConfig":
    """Rescale every length to a different hit spacing.

    Transverse tolerances are deliberately left alone -- see the
    module docstring.
    """
    k = spacing_px / self.spacing_px
    return replace(
      self, spacing_px=spacing_px,
      grow_margin=self.grow_margin * k,
      refine_dl=self.refine_dl * k,
      refine_dl_step=self.refine_dl_step * k,
      refine_dl_min=self.refine_dl_min * k,
      single_point_max_dist=self.single_point_max_dist * k,
      neighbour_xy=self.neighbour_xy * k,
      join_max_overlap=self.join_max_overlap * k,
      join_short_poly=self.join_short_poly * k,
      end_margin=self.end_margin * k,
      end_reach=self.end_reach * k,
      vertex_merge=self.vertex_merge * k,
    )


# The MATLAB constants, unchanged. Every entry point defaults to this,
# so a caller that passes nothing gets the reference behaviour.
MATLAB_CONFIG = DetectorConfig()
