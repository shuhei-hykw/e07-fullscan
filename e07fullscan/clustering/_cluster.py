from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..tracking._track import Track

if TYPE_CHECKING:
    import pandas as pd

_DIST_EPS  = 20.0  # rho tolerance in pixels
_ANGLE_EPS = 5.0   # theta tolerance in degrees


def _hough_params(t: Track) -> tuple[float, float]:
    """Return (rho, theta_deg) Hough normal-form for a track.

    theta is the normal-to-line angle in [0, 180).
    rho is the signed distance from origin to the infinite line.
    All collinear segments share the same (rho, theta).
    """
    theta = (t.angle_deg + 90.0) % 180.0
    theta_rad = math.radians(theta)
    mx = (t.px1 + t.px2) / 2.0
    my = (t.py1 + t.py2) / 2.0
    rho = mx * math.cos(theta_rad) + my * math.sin(theta_rad)
    return rho, theta


def _angle_diff(a1: float, a2: float) -> float:
    """Circular angle difference in [0, 90] degrees."""
    d = abs(a1 - a2) % 180.0
    return min(d, 180.0 - d)


def cluster_tracks(
    tracks: list[Track],
    *,
    dist_eps: float  = _DIST_EPS,
    angle_eps: float = _ANGLE_EPS,
) -> list[Track]:
    """Merge duplicate Hough segments into one representative per cluster.

    Two tracks are in the same cluster when their Hough normal-form
    parameters satisfy |Δrho| < dist_eps (px) and |Δtheta| < angle_eps
    (deg).  The longest segment in each cluster is returned.
    """
    n = len(tracks)
    if n == 0:
        return []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    params = [_hough_params(t) for t in tracks]

    for i in range(n):
        rho_i, theta_i = params[i]
        for j in range(i + 1, n):
            rho_j, theta_j = params[j]
            if (abs(rho_i - rho_j) < dist_eps
                    and _angle_diff(theta_i, theta_j) < angle_eps):
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    return [
        tracks[max(idx_list, key=lambda i: tracks[i].length_px)]
        for idx_list in clusters.values()
    ]


def cluster_df(
    df: "pd.DataFrame",
    *,
    dist_eps: float  = _DIST_EPS,
    angle_eps: float = _ANGLE_EPS,
) -> "pd.DataFrame":
    """Cluster tracks in a DataFrame, one (view_id, slice_idx) group at a time.

    Expects the standard analysis output columns.  Returns a DataFrame
    with the same schema but one representative row per cluster.
    """
    import pandas as pd

    groups: list[pd.DataFrame] = []
    for (view_id, slice_idx), sub in df.groupby(
        ["view_id", "slice_idx"], sort=False
    ):
        tracks = [
            Track(
                x1=float(r.x1), y1=float(r.y1),
                x2=float(r.x2), y2=float(r.y2),
                z=float(r.z),
                px1=int(r.px1), py1=int(r.py1),
                px2=int(r.px2), py2=int(r.py2),
                length_px=float(r.length_px),
                angle_deg=float(r.angle_deg),
                view_id=str(r.view_id),
            )
            for r in sub.itertuples()
        ]
        merged = cluster_tracks(tracks, dist_eps=dist_eps,
                                angle_eps=angle_eps)
        groups.append(pd.DataFrame([{
            "view_id":   t.view_id,
            "slice_idx": slice_idx,
            "x1": t.x1, "y1": t.y1, "x2": t.x2, "y2": t.y2,
            "z":  t.z,
            "px1": t.px1, "py1": t.py1, "px2": t.px2, "py2": t.py2,
            "length_px":   t.length_px,
            "angle_deg":   t.angle_deg,
            "n_grains":    t.n_grains,
            "width_px":    t.width_px,
            "mean_intens": t.mean_intens,
        } for t in merged]))

    if not groups:
        return pd.DataFrame(columns=df.columns)
    return pd.concat(groups, ignore_index=True)
