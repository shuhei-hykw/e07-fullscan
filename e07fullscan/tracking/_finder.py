from __future__ import annotations

import cv2
import numpy as np

from ._track import Track

_ZPJ_HALF   = 4
_FOG_KSIZE  = 51
_NOISE_AMIN = 2
_NOISE_AMAX = 100
_NOISE_CMP  = 50
_HOUGH_THR  = 20
_HOUGH_ML   = 25
_HOUGH_MG   = 4


def _pixel_to_stage(
    affine: list[float], px: float, py: float
) -> tuple[float, float]:
    # affine_p2s layout: [a00, a01, a10, a11, tx, ty]
    # stage_x = a00*px + a01*py + tx
    # stage_y = a10*px + a11*py + ty
    a00, a01, a10, a11, tx, ty = affine
    return a00 * px + a01 * py + tx, a10 * px + a11 * py + ty


def preprocess(
    img: np.ndarray,
    fog_ksize: int  = _FOG_KSIZE,
    noise_amin: int = _NOISE_AMIN,
    noise_amax: int = _NOISE_AMAX,
    noise_cmp: int  = _NOISE_CMP,
) -> np.ndarray:
    """Fog removal → Otsu threshold → noise removal. Returns binary image."""
    k = fog_ksize if fog_ksize % 2 == 1 else fog_ksize + 1
    blurred = cv2.GaussianBlur(img, (k, k), 0)
    current = cv2.subtract(blurred, img)

    _, current = cv2.threshold(
        current, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )

    contours, _ = cv2.findContours(
        current, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    noise = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < noise_amin:
            noise.append(cnt)
            continue
        perimeter = cv2.arcLength(cnt, True)
        if (perimeter > 0 and area < noise_amax
                and (perimeter ** 2) / area < noise_cmp):
            noise.append(cnt)
    cv2.drawContours(current, noise, -1, 0, thickness=-1)
    return current


def find_tracks(
    reader,
    idx: int,
    *,
    view_id: str    = "",
    zpj_half: int   = _ZPJ_HALF,
    fog_ksize: int  = _FOG_KSIZE,
    noise_amin: int = _NOISE_AMIN,
    noise_amax: int = _NOISE_AMAX,
    noise_cmp: int  = _NOISE_CMP,
    hough_thr: int  = _HOUGH_THR,
    hough_min_line: int = _HOUGH_ML,
    hough_max_gap: int  = _HOUGH_MG,
) -> list[Track]:
    """Detect tracks in one Z-slice and return them in stage coordinates.

    Parameters
    ----------
    reader:
        SpngReader for the view.
    idx:
        Target slice index within the reader.
    view_id:
        Identifier stored in each Track (typically the JSON path).
    """
    lo = max(0, idx - zpj_half)
    hi = min(len(reader) - 1, idx + zpj_half)
    slices = [reader.read(i) for i in range(lo, hi + 1)]
    img = np.mean(slices, axis=0).astype(np.uint8)

    binary = preprocess(
        img,
        fog_ksize=fog_ksize,
        noise_amin=noise_amin,
        noise_amax=noise_amax,
        noise_cmp=noise_cmp,
    )

    lines = cv2.HoughLinesP(
        binary, 1, np.pi / 180,
        threshold=hough_thr,
        minLineLength=hough_min_line,
        maxLineGap=hough_max_gap,
    )
    if lines is None:
        return []

    entry = reader.entries[idx]
    affine = reader.affine_p2s
    tracks = []
    for x1p, y1p, x2p, y2p in lines[:, 0]:
        sx1, sy1 = _pixel_to_stage(affine, float(x1p), float(y1p))
        sx2, sy2 = _pixel_to_stage(affine, float(x2p), float(y2p))
        length = float(np.hypot(x2p - x1p, y2p - y1p))
        angle = float(
            np.degrees(np.arctan2(y2p - y1p, x2p - x1p)) % 180
        )
        tracks.append(Track(
            x1=sx1, y1=sy1,
            x2=sx2, y2=sy2,
            z=entry.z,
            px1=int(x1p), py1=int(y1p),
            px2=int(x2p), py2=int(y2p),
            length_px=length,
            angle_deg=angle,
            view_id=view_id,
        ))
    return tracks
