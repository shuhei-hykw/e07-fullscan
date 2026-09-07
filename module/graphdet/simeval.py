"""Score the graph detector against the MATLAB simulation truth.

``e07/matlab/simdata8.mat`` is the only place this pipeline has ground
truth. ``Summary`` lists every simulated track's start and end, and an
endpoint shared by two or more tracks is a real branch point -- the
calculation is spelled out but commented out at detect_tracks.m L61-64.

Everything here works in isotropic coordinates: one slice is ~10 px at
the simulation's 3 um spacing, so a raw Euclidean distance would treat
a one-slice error as a one-pixel one.
"""
from __future__ import annotations

import numpy as np

from .branch import attachment_codes, branch_points, detect_branches
from .detectlseg import detect_lseg_view
from .config import MATLAB_CONFIG, MATLAB_Z_SCALE, DetectorConfig
from .geom import scale_z
from .integrate import integrate_smallregions

# Columns of Summary holding the start and end coordinates.
_START_COLS = slice(1, 4)
_END_COLS = slice(4, 7)


def true_branch_points(summary: np.ndarray):
  """Endpoints shared by two or more simulated tracks, and how many."""
  pts = np.vstack([summary[:, _START_COLS], summary[:, _END_COLS]])
  uniq, counts = np.unique(pts, axis=0, return_counts=True)
  return uniq[counts > 1], counts[counts > 1]


def run_pipeline(hits: np.ndarray, cfg: DetectorConfig = MATLAB_CONFIG,
                 **kwargs) -> dict:
  """All three stages on one view. kwargs go to detect_lseg_view."""
  segments, _ = detect_lseg_view(hits, cfg=cfg, **kwargs)
  polylines = integrate_smallregions(hits, segments, cfg)
  if not polylines:
    return {"segments": segments, "polylines": [],
            "group_id": np.zeros(0, dtype=np.int64),
            "points": np.zeros((0, 3)), "mult": np.zeros(0, dtype=np.int64)}
  codes = attachment_codes(polylines, hits, cfg)
  _, group_id = detect_branches(polylines, hits, codes, cfg)
  points, mult = branch_points(polylines, hits, codes, cfg)
  return {"segments": segments, "polylines": polylines,
          "group_id": group_id, "points": points, "mult": mult}


def match_branch_points(
  truth: np.ndarray, found: np.ndarray, z_scale: float = MATLAB_Z_SCALE,
):
  """Isotropic distances between true and reconstructed vertices.

  Returns (per-truth nearest distance, per-found nearest distance,
  index of the nearest found vertex for each true one).
  """
  if truth.shape[0] == 0 or found.shape[0] == 0:
    return (np.full(truth.shape[0], np.inf),
            np.full(found.shape[0], np.inf),
            np.zeros(truth.shape[0], dtype=np.int64))
  d = np.linalg.norm(
    scale_z(truth[:, None, :] - found[None, :, :], z_scale), axis=2)
  return d.min(axis=1), d.min(axis=0), d.argmin(axis=1)


def score(truth: np.ndarray, found: np.ndarray, tolerance: float,
          z_scale: float = MATLAB_Z_SCALE) -> dict:
  """Efficiency, purity and how many true vertices got merged."""
  to_truth, to_found, nearest = match_branch_points(truth, found, z_scale)
  hit = to_truth <= tolerance
  # Several true vertices a few pixels apart can collapse onto one
  # reconstructed vertex; counting each as "found" overstates how well
  # the detector resolves them.
  merged = int(hit.sum() - np.unique(nearest[hit]).size)
  return {
    "n_truth": int(truth.shape[0]), "n_found": int(found.shape[0]),
    "matched_truth": int(hit.sum()),
    "matched_found": int((to_found <= tolerance).sum()),
    "merged": merged,
    "efficiency": float(hit.mean()) if truth.shape[0] else float("nan"),
    "purity": (float((to_found <= tolerance).mean())
               if found.shape[0] else float("nan")),
  }
