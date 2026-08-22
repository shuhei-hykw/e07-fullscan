"""Python port of the MATLAB graph track detector (``e07/matlab``).

Stage 1 (``detectlseg``) is ported; ``integrate_smallregions`` and
``detectbunki`` follow. See README.md for the porting plan and how to
check a stage against ``e07/matlab/work1.mat``.
"""
from .detectlseg import (
  detect_lseg_smallregion, detect_lseg_view, grow_segments, iter_regions,
  refine_endpoints, split_into_linear_components,
)

__all__ = [
  "detect_lseg_smallregion", "detect_lseg_view", "grow_segments",
  "iter_regions", "refine_endpoints", "split_into_linear_components",
]
