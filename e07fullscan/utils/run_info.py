"""Run metadata utilities for output traceability.

Provides run_id generation, JSON sidecar writing, and parquet metadata
embedding so every output file can be traced back to the exact parameters
that produced it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _git_hash() -> str:
  """Return short git commit hash, or 'unknown' if unavailable."""
  try:
    result = subprocess.run(
      ["git", "rev-parse", "--short", "HEAD"],
      capture_output=True, text=True, check=True,
      cwd=Path(__file__).resolve().parents[2],
    )
    return result.stdout.strip()
  except Exception:
    return "unknown"


def make_run_id() -> str:
  """Return YYYYMMDD_HHMMSS_<git_short_hash>."""
  now = datetime.now()
  return f"{now.strftime('%Y%m%d_%H%M%S')}_{_git_hash()}"


def build_run_meta(
  run_id: str,
  script: str,
  params: dict[str, Any],
) -> dict[str, Any]:
  """Build a run metadata dictionary."""
  return {
    "run_id": run_id,
    "script": Path(script).name,
    "timestamp": datetime.now().isoformat(),
    "python": sys.version.split()[0],
    "params": params,
  }


def save_run_json(
  meta: dict[str, Any],
  output_path: Path,
) -> Path:
  """Save run metadata as a JSON sidecar next to output_path.

  For a file foo.parquet → foo_run.json.
  For a directory        → <dir>/run_params.json.
  """
  output_path = Path(output_path)
  if output_path.is_dir():
    json_path = output_path / "run_params.json"
  elif not output_path.suffix:
    json_path = output_path / "run_params.json"
  else:
    json_path = output_path.with_name(
      output_path.stem + "_run.json"
    )
  json_path.parent.mkdir(parents=True, exist_ok=True)
  with json_path.open("w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2, default=str)
  return json_path


def save_parquet_with_meta(
  df: "pd.DataFrame",
  output_path: Path,
  meta: dict[str, Any],
) -> None:
  """Save DataFrame to parquet with run metadata in schema metadata."""
  import pyarrow as pa
  import pyarrow.parquet as pq

  table = pa.Table.from_pandas(df)
  existing = dict(table.schema.metadata or {})
  existing[b"run_meta"] = json.dumps(meta, default=str).encode()
  table = table.replace_schema_metadata(existing)
  output_path = Path(output_path)
  output_path.parent.mkdir(parents=True, exist_ok=True)
  pq.write_table(table, output_path)
