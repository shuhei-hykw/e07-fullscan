"""
Reader for the SPNG image format used in E07 emulsion full scanning.

Format:
  - JSON file  : metadata for one view stack (ImageType, Images list, ...)
  - SPNG file  : binary container of PNG blobs referenced by the JSON as
                 "filename.spng&byte_offset&byte_length"
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np


@dataclass(frozen=True)
class ImageEntry:
    """Byte-range descriptor and stage position for a single image inside an SPNG file."""
    spng_path: Path
    offset: int
    length: int
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class ImageType:
    depth: int
    height: int
    width: int


class SpngReader:
    """
    Reads a z-stack from a paired JSON + SPNG file.

    Parameters
    ----------
    json_path:
        Path to the JSON metadata file (*.json).
    """

    def __init__(self, json_path: Path | str) -> None:
        self._json_path = Path(json_path)
        self._base_dir = self._json_path.parent

        with self._json_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)

        self._entries: list[ImageEntry] = self._parse_entries(meta)
        self.image_type = ImageType(
            depth=meta["ImageType"]["Depth"],
            height=meta["ImageType"]["Height"],
            width=meta["ImageType"]["Width"],
        )
        self.affine_p2s: list[float] = meta.get("AffineP2S", [1, 0, 0, 1, 0, 0])
        self.datetime: str = meta.get("DateTime", "")

    def _parse_entries(self, meta: dict) -> list[ImageEntry]:
        entries: list[ImageEntry] = []
        for img in meta.get("Images", []):
            filename, offset_s, length_s = img["Path"].split("&")
            entries.append(ImageEntry(
                spng_path=self._base_dir / filename,
                offset=int(offset_s),
                length=int(length_s),
                x=float(img.get("x", 0.0)),
                y=float(img.get("y", 0.0)),
                z=float(img.get("z", 0.0)),
            ))
        return entries

    # ------------------------------------------------------------------
    # Container protocol
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[np.ndarray]:
        for i in range(len(self)):
            yield self.read(i)

    def __getitem__(self, idx: int) -> np.ndarray:
        return self.read(idx)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def entries(self) -> list[ImageEntry]:
        """Metadata for every image in the stack (read-only view)."""
        return list(self._entries)

    def z_positions(self) -> np.ndarray:
        """Z positions of all images as a 1-D float64 array."""
        return np.array([e.z for e in self._entries], dtype=np.float64)

    def read_raw(self, idx: int) -> bytes:
        """Return the raw PNG bytes for image *idx* without decoding."""
        entry = self._entries[idx]
        with entry.spng_path.open("rb") as f:
            f.seek(entry.offset)
            return f.read(entry.length)

    def read(self, idx: int) -> np.ndarray:
        """
        Decode image *idx* and return it as a 2-D uint8 array (H × W).

        Raises
        ------
        ValueError
            If cv2 fails to decode the stored PNG blob.
        """
        entry = self._entries[idx]
        with entry.spng_path.open("rb") as f:
            raw = np.fromfile(f, dtype=np.uint8, count=entry.length, offset=entry.offset)
        img = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(
                f"Failed to decode image at index {idx} in {entry.spng_path}"
            )
        return img

    def read_stack(self) -> np.ndarray:
        """Read all images and return them as an (N, H, W) uint8 array."""
        return np.stack([self.read(i) for i in range(len(self))], axis=0)


def load_spng(json_path: Path | str) -> SpngReader:
    """Open an SPNG view stack from its JSON metadata file."""
    return SpngReader(json_path)
