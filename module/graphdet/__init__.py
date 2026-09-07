"""Python port of the MATLAB graph track detector (``e07/matlab``).

Stage 1 (``detectlseg``) and stage 2 (``integrate_smallregions``) are
ported; ``detectbunki`` follows. See README.md for the porting plan and
how to check a stage against ``e07/matlab/work1.mat``.
"""
from .detectlseg import (
  detect_lseg_smallregion, detect_lseg_view, grow_segments, iter_regions,
  refine_endpoints, split_into_linear_components,
)
from .integrate import integrate_smallregions
from .polyfit import inflection_nodes, pixellist_to_poly

__all__ = [
  "detect_lseg_smallregion", "detect_lseg_view", "grow_segments",
  "inflection_nodes", "integrate_smallregions", "iter_regions",
  "pixellist_to_poly", "refine_endpoints", "split_into_linear_components",
]
