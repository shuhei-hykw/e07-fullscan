"""Python port of the MATLAB graph track detector (``e07/matlab``).

All three stages are ported: ``detectlseg`` (segments per sub-region),
``integrate_smallregions`` (segments into tracks) and ``detectbunki``
(tracks into branch groups). See README.md for how each stage is
checked against ``e07/matlab/work1.mat``.
"""
from .config import (
  E07_SPACING_PX, E07_Z_SCALE, MATLAB_CONFIG, MATLAB_SPACING_PX,
  MATLAB_Z_SCALE, DetectorConfig,
)
from .branch import (
  attachment_codes, branch_adjacency, branch_points, detect_branches,
  junction_hits,
)
from .downsample import mabiki
from .detectlseg import (
  detect_lseg_smallregion, detect_lseg_view, grow_segments, iter_regions,
  refine_endpoints, split_into_linear_components,
)
from .integrate import integrate_smallregions
from .polyfit import inflection_nodes, pixellist_to_poly
from .simeval import (
  match_branch_points, run_pipeline, score, true_branch_points,
)

__all__ = [
  "DetectorConfig", "E07_SPACING_PX", "E07_Z_SCALE", "MATLAB_CONFIG",
  "MATLAB_SPACING_PX", "MATLAB_Z_SCALE",
  "attachment_codes", "branch_adjacency", "branch_points",
  "detect_branches", "detect_lseg_smallregion", "detect_lseg_view",
  "grow_segments", "inflection_nodes", "integrate_smallregions",
  "iter_regions", "junction_hits", "mabiki", "match_branch_points",
  "pixellist_to_poly", "refine_endpoints", "run_pipeline", "score",
  "split_into_linear_components", "true_branch_points",
]
