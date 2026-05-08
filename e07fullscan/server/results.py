"""Stored track results access and rendering for the web viewer."""
from __future__ import annotations

from pathlib import Path

import cv2
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


class ResultsStore:
    """In-memory store for pre-computed track results."""

    def __init__(self, path: Path) -> None:
        path = Path(path)
        if path.is_dir() or path.suffix == ".parquet":
            self._df = pd.read_parquet(path)
        else:
            import sqlite3
            with sqlite3.connect(path) as conn:
                self._df = pd.read_sql(
                    "SELECT * FROM tracks", conn
                )

    def get_slice(
        self, view_id: str, slice_idx: int
    ) -> pd.DataFrame:
        mask = (
            (self._df["view_id"] == view_id)
            & (self._df["slice_idx"] == slice_idx)
        )
        return self._df[mask]

    def view_ids(self) -> list[str]:
        return sorted(self._df["view_id"].unique().tolist())

    def slice_indices(self, view_id: str) -> list[int]:
        sub = self._df[self._df["view_id"] == view_id]
        return sorted(sub["slice_idx"].unique().tolist())


def render_image(
    df: pd.DataFrame, height: int, width: int
) -> np.ndarray:
    """Draw stored track segments as green lines on black."""
    out = np.zeros((height, width, 3), dtype=np.uint8)
    for row in df.itertuples():
        cv2.line(
            out,
            (int(row.px1), int(row.py1)),
            (int(row.px2), int(row.py2)),
            (0, 255, 0), 1,
        )
    return out


def _ax_style(ax) -> None:
    ax.set_facecolor("#111111")
    ax.tick_params(colors="#888888", labelsize=7)
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.xaxis.label.set_color("#aaaaaa")
    ax.yaxis.label.set_color("#aaaaaa")
    ax.title.set_color("#cccccc")
    ax.title.set_fontsize(9)


def render_stats(df: pd.DataFrame) -> plt.Figure:
    """Angle + length histograms for a single slice."""
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(10, 4), facecolor="#1a1a1a",
        gridspec_kw={"wspace": 0.35},
    )
    for ax in (ax1, ax2):
        _ax_style(ax)

    n = len(df)
    fig.suptitle(
        f"Stored results — {n} track(s)",
        color="#cccccc", fontsize=9, family="monospace", y=0.99,
    )

    ax1.set_title("Track Angle Distribution")
    ax1.set_xlabel("angle (deg, 0–180)")
    ax1.set_ylabel("count")
    if n:
        ax1.hist(
            df["angle_deg"].astype(float),
            bins=36, range=(0, 180),
            color="#ffaa44", alpha=0.85,
        )
        ax1.set_xlim(0, 180)
        ax1.set_xticks(range(0, 181, 30))
    else:
        ax1.text(0.5, 0.5, "no tracks",
                 transform=ax1.transAxes,
                 ha="center", va="center", color="#666666")

    ax2.set_title("Track Length Distribution")
    ax2.set_xlabel("length (px)")
    ax2.set_ylabel("count")
    if n:
        ax2.hist(
            df["length_px"].astype(float),
            bins=40, color="#44ff88", alpha=0.85,
        )
        ax2.text(0.97, 0.95, f"n={n}",
                 transform=ax2.transAxes, ha="right", va="top",
                 color="#aaaaaa", fontsize=8)
    else:
        ax2.text(0.5, 0.5, "no tracks",
                 transform=ax2.transAxes,
                 ha="center", va="center", color="#666666")

    return fig
