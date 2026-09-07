"""Tunable constants of the graph detector, in one place.

The MATLAB originals were tuned on a simulation that samples a track
every ~3 px. The real E07 export samples every 30 px
(``matlab_export._GRID_CELL_PX``), and at that spacing several of
these constants span less than a single gap between hits, so the step
they gate never fires. Collecting them here is what makes that
testable: ``scripts/scan_sampling.py`` re-thins the same simulation at
other block sizes, so the truth stays intact while the spacing
changes.

Constants split three ways, and which group a constant belongs to was
settled by measurement, not by reading the code.

**Hit-spacing scales** -- how far to look for the NEXT HIT. These must
grow with the spacing or the step they gate never fires, and
``for_spacing`` scales exactly these.

**Transverse tolerances** -- distances measured ACROSS a track, i.e.
its width plus measurement error. These do not grow: the E07 export
skeletonises each component before sampling, so its hits sit on the
centreline however coarse the grid is.

**Track-geometry gaps** -- how far apart two reconstructed PIECES of
one track may be, or how far a track may stop short of a vertex. These
are set by the physics and by the sub-region grid, not by how densely
the track was sampled, so they do not grow either. Scaling them was
tried and is worse: on the simulation re-thinned to 6 px, scaling
everything gives 90.2% efficiency at 66.0% purity, while scaling only
the hit-spacing group gives 87.8% at 75.5% -- and purity is the weak
side. At 10 px the gap is wider still (54.0% against 67.3%). It also
costs dearly in runtime, because a 10x larger endpoint search box
turns stage 2's chaining quadratic on real data.
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

  # -- hit-spacing scales (for_spacing scales exactly these) ---------
  # How far past its own extent a component looks for more hits.
  grow_margin: float = 20.0
  # Endpoint refinement: how far an endpoint may slide, in what steps,
  # and the step below which refining stops.
  refine_dl: float = 20.0
  refine_dl_step: float = 5.0
  refine_dl_min: float = 2.0
  # isaline5: two single-hit components this close are one track.
  single_point_max_dist: float = 20.0

  # -- track-geometry gaps (do NOT scale; see the module docstring) --
  # Half-widths of the box searched for an endpoint to continue a
  # track into. Set by where the sub-region grid cuts a track, not by
  # the sampling. z is in slices, and a slice is ~10 px, hence far
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
    """Rescale the hit-spacing group to a different hit spacing.

    Transverse tolerances and track-geometry gaps are deliberately
    left alone -- see the module docstring for the measurement that
    settled it.
    """
    k = spacing_px / self.spacing_px
    return replace(
      self, spacing_px=spacing_px,
      grow_margin=self.grow_margin * k,
      refine_dl=self.refine_dl * k,
      refine_dl_step=self.refine_dl_step * k,
      refine_dl_min=self.refine_dl_min * k,
      single_point_max_dist=self.single_point_max_dist * k,
    )


# The MATLAB constants, unchanged. Every entry point defaults to this,
# so a caller that passes nothing gets the reference behaviour.
MATLAB_CONFIG = DetectorConfig()
