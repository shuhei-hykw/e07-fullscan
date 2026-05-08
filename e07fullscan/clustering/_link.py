"""Cross-slice track linking: connect 2D segments into 3D tracks."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ._cluster import _angle_diff

if TYPE_CHECKING:
    import pandas as pd

_MAX_DIST  = 30.0  # max midpoint distance between adjacent slices (px)
_ANGLE_EPS = 5.0   # max angle difference (deg)


def _midpoints(sub: "pd.DataFrame") -> np.ndarray:
    mx = (sub["px1"].to_numpy() + sub["px2"].to_numpy()) / 2.0
    my = (sub["py1"].to_numpy() + sub["py2"].to_numpy()) / 2.0
    return np.column_stack([mx, my])


def link_tracks(
    df: "pd.DataFrame",
    *,
    max_dist: float  = _MAX_DIST,
    angle_eps: float = _ANGLE_EPS,
) -> "pd.DataFrame":
    """Add a ``track_id`` column grouping segments into 3D tracks.

    Segments in adjacent Z-slices are linked when their midpoints are
    within *max_dist* pixels and their angles agree within *angle_eps*
    degrees.  Only mutual nearest-neighbour pairs are linked (each
    segment participates in at most one link per slice boundary).

    Segments that never link to another slice get a unique track_id of
    their own.
    """
    import pandas as pd

    df = df.copy()
    n = len(df)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for _, vdf in df.groupby("view_id", sort=False):
        slices = sorted(vdf["slice_idx"].unique())

        for s_cur, s_nxt in zip(slices[:-1], slices[1:]):
            cur = vdf[vdf["slice_idx"] == s_cur]
            nxt = vdf[vdf["slice_idx"] == s_nxt]
            if len(cur) == 0 or len(nxt) == 0:
                continue

            cur_pts = _midpoints(cur)
            nxt_pts = _midpoints(nxt)
            cur_ix  = cur.index.to_numpy()
            nxt_ix  = nxt.index.to_numpy()
            cur_ang = cur["angle_deg"].to_numpy()
            nxt_ang = nxt["angle_deg"].to_numpy()

            # pairwise distances (cur x nxt)
            diff = (
                cur_pts[:, np.newaxis, :]    # (C, 1, 2)
                - nxt_pts[np.newaxis, :, :]  # (1, N, 2)
            )
            dist_mat = np.hypot(diff[:, :, 0], diff[:, :, 1])  # (C, N)

            nn_cn = dist_mat.argmin(axis=1)      # best nxt for each cur
            d_cn  = dist_mat[np.arange(len(cur_pts)), nn_cn]
            nn_nc = dist_mat.argmin(axis=0)      # best cur for each nxt
            d_nc  = dist_mat[nn_nc, np.arange(len(nxt_pts))]

            for i, (dist, j) in enumerate(zip(d_cn, nn_cn)):
                if dist > max_dist:
                    continue
                # must be mutual nearest neighbours
                if nn_nc[j] != i:
                    continue
                if d_nc[j] > max_dist:
                    continue
                if _angle_diff(cur_ang[i], nxt_ang[j]) >= angle_eps:
                    continue
                union(int(cur_ix[i]), int(nxt_ix[j]))

    # compress roots → contiguous track_ids
    roots   = [find(i) for i in range(n)]
    uniq    = {r: k for k, r in enumerate(dict.fromkeys(roots))}
    df["track_id"] = [uniq[r] for r in roots]
    return df
