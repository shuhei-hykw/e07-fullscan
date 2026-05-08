"""Batch track finder for E07 full-scan data (e07analyze)."""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

import yaml

from e07fullscan.io import load_spng
from e07fullscan.tracking import find_tracks

_CFG_PATH = Path(__file__).parents[2] / "config" / "default.yaml"

_FIELDS = [
    "view_id", "slice_idx",
    "x1", "y1", "x2", "y2", "z",
    "length_px", "angle_deg",
]

_NUMERIC_FIELDS = ("x1", "y1", "x2", "y2", "z", "length_px", "angle_deg")


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


def _chunk(
    jsons: list[Path], chunk_id: int, chunk_total: int
) -> list[Path]:
    size = math.ceil(len(jsons) / chunk_total)
    lo = chunk_id * size
    return jsons[lo: lo + size]


def _make_row(t, idx: int) -> dict:
    return {
        "view_id":   t.view_id,
        "slice_idx": idx,
        "x1": f"{t.x1:.4f}", "y1": f"{t.y1:.4f}",
        "x2": f"{t.x2:.4f}", "y2": f"{t.y2:.4f}",
        "z":  f"{t.z:.4f}",
        "length_px": f"{t.length_px:.2f}",
        "angle_deg": f"{t.angle_deg:.2f}",
    }


def _analyze_view(
    json_path: Path,
    cfg: dict,
    slice_idx: int | None,
    verbose: bool,
) -> list[dict]:
    reader = load_spng(json_path)
    indices = (
        [slice_idx] if slice_idx is not None else range(len(reader))
    )
    rows = []
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
        rows.extend(_make_row(t, idx) for t in tracks)
    if verbose:
        print(
            f"  {json_path.name}: {len(rows)} tracks",
            file=sys.stderr,
        )
    return rows


def _write_parquet(rows: list[dict], path: Path) -> None:
    import pandas as pd
    df = pd.DataFrame(rows, columns=_FIELDS)
    for col in _NUMERIC_FIELDS:
        df[col] = df[col].astype(float)
    df["slice_idx"] = df["slice_idx"].astype(int)
    df.to_parquet(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="e07analyze",
        description="Batch track finder for E07 full-scan data.",
    )
    parser.add_argument(
        "path", type=Path,
        help="Data directory or single JSON file.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None, metavar="FILE",
        help=(
            "Output file (.parquet or .csv; "
            "default: CSV to stdout)."
        ),
    )
    parser.add_argument(
        "--config", type=Path, default=None, metavar="YAML",
        help="Config YAML (default: config/default.yaml).",
    )
    parser.add_argument(
        "--slice", type=int, default=None, metavar="IDX",
        help="Analyze a single slice index only.",
    )
    parser.add_argument(
        "--chunk-id", type=int, default=None, metavar="N",
        help="Process Nth chunk (0-based, requires --chunk-total).",
    )
    parser.add_argument(
        "--chunk-total", type=int, default=None, metavar="M",
        help="Split JSON list into M equal chunks.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print progress to stderr.",
    )
    args = parser.parse_args()

    if (args.chunk_id is None) != (args.chunk_total is None):
        parser.error(
            "--chunk-id and --chunk-total must be used together."
        )

    cfg   = _load_cfg(args.config)
    jsons = _find_jsons(args.path)
    if not jsons:
        print(
            f"No JSON files found under {args.path}",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.chunk_total is not None:
        jsons = _chunk(jsons, args.chunk_id, args.chunk_total)
        if not jsons:
            print("Empty chunk — nothing to do.", file=sys.stderr)
            sys.exit(0)

    if args.verbose:
        print(f"Processing {len(jsons)} JSON file(s).", file=sys.stderr)

    use_parquet = (
        args.output is not None
        and args.output.suffix == ".parquet"
    )

    if use_parquet:
        all_rows: list[dict] = []
        for json_path in jsons:
            try:
                all_rows.extend(
                    _analyze_view(
                        json_path, cfg, args.slice, args.verbose
                    )
                )
            except Exception as exc:
                print(
                    f"WARNING: {json_path}: {exc}", file=sys.stderr
                )
        _write_parquet(all_rows, args.output)
        if args.verbose:
            print(
                f"Done. {len(all_rows)} tracks → {args.output}",
                file=sys.stderr,
            )
    else:
        out = (
            open(args.output, "w", newline="", encoding="utf-8")
            if args.output else sys.stdout
        )
        try:
            writer = csv.DictWriter(out, fieldnames=_FIELDS)
            writer.writeheader()
            total = 0
            for json_path in jsons:
                try:
                    rows = _analyze_view(
                        json_path, cfg, args.slice, args.verbose
                    )
                    writer.writerows(rows)
                    total += len(rows)
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
