"""Batch track finder for E07 full-scan data (e07analyze)."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import yaml

from e07fullscan.io import load_spng
from e07fullscan.tracking import find_tracks

_CFG_PATH = Path(__file__).parents[2] / "config" / "default.yaml"

_CSV_FIELDS = [
    "view_id", "slice_idx",
    "x1", "y1", "x2", "y2", "z",
    "length_px", "angle_deg",
]


def _load_cfg(path: Path | None) -> dict:
    p = path or _CFG_PATH
    if p.exists():
        raw = yaml.safe_load(p.read_text()) or {}
        return raw.get("viewer", {})
    return {}


def _find_jsons(path: Path) -> list[Path]:
    if path.is_file() and path.suffix == ".json":
        return [path]
    return sorted(path.rglob("*.json"))


def _analyze_view(
    json_path: Path,
    cfg: dict,
    writer: csv.DictWriter,
    slice_idx: int | None,
    verbose: bool,
) -> int:
    reader = load_spng(json_path)
    indices = (
        [slice_idx] if slice_idx is not None else range(len(reader))
    )
    n_total = 0
    for idx in indices:
        tracks = find_tracks(
            reader, idx,
            view_id=str(json_path),
            zpj_half=cfg.get("zpj_half", 4),
            fog_ksize=cfg.get("fog_ksize", 51),
            noise_amin=cfg.get("noise_amin", 2),
            noise_amax=cfg.get("noise_amax", 100),
            noise_cmp=cfg.get("noise_cmp", 50),
            hough_thr=cfg.get("hough_thr", 20),
            hough_min_line=cfg.get("hough_ml", 25),
            hough_max_gap=cfg.get("hough_mg", 4),
        )
        for t in tracks:
            writer.writerow({
                "view_id":   t.view_id,
                "slice_idx": idx,
                "x1": f"{t.x1:.4f}",
                "y1": f"{t.y1:.4f}",
                "x2": f"{t.x2:.4f}",
                "y2": f"{t.y2:.4f}",
                "z":  f"{t.z:.4f}",
                "length_px": f"{t.length_px:.2f}",
                "angle_deg": f"{t.angle_deg:.2f}",
            })
        n_total += len(tracks)
    if verbose:
        print(
            f"  {json_path.name}: {n_total} tracks",
            file=sys.stderr,
        )
    return n_total


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="e07analyze",
        description="Batch track finder for E07 full-scan data.",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Data directory or single JSON file.",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        metavar="FILE",
        help="Output CSV file (default: stdout).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="YAML",
        help="Config YAML (default: config/default.yaml).",
    )
    parser.add_argument(
        "--slice",
        type=int,
        default=None,
        metavar="IDX",
        help="Analyze a single slice index only.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print progress to stderr.",
    )
    args = parser.parse_args()

    cfg   = _load_cfg(args.config)
    jsons = _find_jsons(args.path)
    if not jsons:
        print(
            f"No JSON files found under {args.path}",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.verbose:
        print(f"Found {len(jsons)} JSON file(s).", file=sys.stderr)

    out = (
        open(args.output, "w", newline="", encoding="utf-8")
        if args.output else sys.stdout
    )
    try:
        writer = csv.DictWriter(out, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        total = 0
        for json_path in jsons:
            try:
                total += _analyze_view(
                    json_path, cfg, writer,
                    slice_idx=args.slice,
                    verbose=args.verbose,
                )
            except Exception as exc:
                print(
                    f"WARNING: {json_path}: {exc}",
                    file=sys.stderr,
                )
    finally:
        if args.output:
            out.close()

    if args.verbose:
        print(f"Done. Total tracks: {total}", file=sys.stderr)


if __name__ == "__main__":
    main()
