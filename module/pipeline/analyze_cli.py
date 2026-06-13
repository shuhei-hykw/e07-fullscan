"""Batch track finder for E07 full-scan data (e07analyze)."""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from pathlib import Path

import yaml

from module.reader import load_spng
from module.pipeline import find_tracks

_CFG_PATH = Path(__file__).parents[2] / "config" / "default.yaml"

_FIELDS = [
  "view_id", "slice_idx",
  "x1", "y1", "x2", "y2", "z",
  "px1", "py1", "px2", "py2",
  "length_px", "angle_deg",
  "n_grains", "width_px", "mean_intens", "grain_density",
  "px_scale_um", "view_x_mm", "view_y_mm",
]

_NUMERIC_FIELDS = (
  "x1", "y1", "x2", "y2", "z",
  "length_px", "angle_deg", "width_px", "mean_intens", "grain_density",
  "px_scale_um", "view_x_mm", "view_y_mm",
)
_INT_FIELDS = ("slice_idx", "px1", "py1", "px2", "py2", "n_grains")


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


def _grain_density(t) -> str:
  """Grain density: grains/100μm when px_scale_um>0, else grains/px."""
  if t.length_px <= 0:
    return "0.0000"
  if t.px_scale_um > 0:
    length_um = t.length_px * t.px_scale_um
    return f"{t.n_grains / length_um * 100:.4f}"
  return f"{t.n_grains / t.length_px:.4f}"


def _make_row(t, idx: int) -> dict:
  return {
    "view_id":   t.view_id,
    "slice_idx": idx,
    "x1": f"{t.x1:.4f}", "y1": f"{t.y1:.4f}",
    "x2": f"{t.x2:.4f}", "y2": f"{t.y2:.4f}",
    "z":  f"{t.z:.4f}",
    "px1": t.px1, "py1": t.py1,
    "px2": t.px2, "py2": t.py2,
    "length_px": f"{t.length_px:.2f}",
    "angle_deg": f"{t.angle_deg:.2f}",
    "n_grains":      t.n_grains,
    "width_px":      f"{t.width_px:.3f}",
    "mean_intens":   f"{t.mean_intens:.3f}",
    "grain_density":  _grain_density(t),
    "px_scale_um":   f"{t.px_scale_um:.4f}",
    "view_x_mm":     f"{t.view_x_mm:.6f}",
    "view_y_mm":     f"{t.view_y_mm:.6f}",
  }


def _analyze_view(
  json_path: Path,
  cfg: dict,
  slice_idx: int | None,
  verbose: bool,
  cv_threads: int = 0,
) -> list[dict]:
  import cv2
  if cv_threads > 0:
    cv2.setNumThreads(cv_threads)

  reader = load_spng(json_path)
  indices = (
    [slice_idx] if slice_idx is not None else range(len(reader))
  )

  # Pre-load all slices once to avoid 9× redundant imdecode per slice
  stack = reader.read_stack()  # (N, H, W) uint8

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
      noise_amax_upper=cfg.get("noise_amax_upper", 0),
      hough_thr=cfg.get("hough_thr", 20),
      hough_min_line=cfg.get("hough_ml", 25),
      hough_max_gap=cfg.get("hough_mg", 4),
      grain_radius=cfg.get("grain_radius", 10),
      px_scale_um=cfg.get("px_scale_um", 0.0),
      _stack=stack,
    )
    rows.extend(_make_row(t, idx) for t in tracks)
  if verbose:
    print(
      f"  {json_path.name}: {len(rows)} tracks",
      file=sys.stderr,
    )
  return rows


def _analyze_view_worker(args: tuple) -> list[dict]:
  """Top-level wrapper so ProcessPoolExecutor can pickle it."""
  return _analyze_view(*args)


def _write_parquet(rows: list[dict], path: Path) -> None:
  import pandas as pd
  df = pd.DataFrame(rows, columns=_FIELDS)
  for col in _NUMERIC_FIELDS:
    df[col] = df[col].astype(float)
  for col in _INT_FIELDS:
    df[col] = df[col].astype(int)
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
  parser.add_argument(
    "-j", "--workers", type=int, default=1, metavar="N",
    help=(
      "Parallel worker processes (default: 1). "
      "Set to 0 for os.cpu_count()."
    ),
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

  workers = args.workers if args.workers > 0 else os.cpu_count() or 1
  # When using multiple workers, limit OpenCV threads per process to
  # avoid CPU oversubscription (workers × cv_threads ≈ cpu_count).
  cv_threads = max(1, (os.cpu_count() or 1) // workers) if workers > 1 else 0

  if args.verbose:
    print(
      f"Processing {len(jsons)} JSON file(s) "
      f"with {workers} worker(s).",
      file=sys.stderr,
    )

  use_parquet = (
    args.output is not None
    and args.output.suffix == ".parquet"
  )

  def _run_sequential(jsons):
    all_rows: list[dict] = []
    for json_path in jsons:
      try:
        all_rows.extend(
          _analyze_view(
            json_path, cfg, args.slice,
            args.verbose, cv_threads,
          )
        )
      except Exception as exc:
        print(f"WARNING: {json_path}: {exc}",
              file=sys.stderr)
    return all_rows

  def _run_parallel(jsons, workers):
    from concurrent.futures import ProcessPoolExecutor, as_completed
    task_args = [
      (p, cfg, args.slice, args.verbose, cv_threads)
      for p in jsons
    ]
    all_rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
      futs = {ex.submit(_analyze_view_worker, a): a[0]
              for a in task_args}
      for fut in as_completed(futs):
        try:
          all_rows.extend(fut.result())
        except Exception as exc:
          print(f"WARNING: {futs[fut]}: {exc}",
                file=sys.stderr)
    return all_rows

  runner = _run_parallel if workers > 1 else _run_sequential

  if use_parquet:
    all_rows = runner(jsons, workers) if workers > 1 \
      else runner(jsons)
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
      rows = runner(jsons, workers) if workers > 1 \
        else runner(jsons)
      writer.writerows(rows)
      total = len(rows)
    finally:
      if args.output:
        out.close()
    if args.verbose:
      print(f"Done. Total tracks: {total}", file=sys.stderr)


if __name__ == "__main__":
  main()
