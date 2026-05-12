"""E07 pipeline status — run with no arguments.

  python scripts/status.py

Shows KEKCC jobs and completion state of each pipeline stage.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

# ── project root (one level up from this script) ──────────────────────
ROOT    = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

N_CHUNKS = 135   # expected number of KEKCC array jobs


# ── helpers ───────────────────────────────────────────────────────────

def _count(pattern: str) -> int:
  return len(list(RESULTS.glob(pattern)))


def _parquet_rows(path: Path) -> str:
  """Return row count string, or '?' on error."""
  try:
    import pyarrow.parquet as pq
    n = pq.read_metadata(path).num_rows
    return f"{n:,}"
  except Exception:
    return "?"


def _bar(done: int, total: int, width: int = 20) -> str:
  filled = int(width * done / max(total, 1))
  return f"[{'█' * filled}{'░' * (width - filled)}] {done}/{total}"


def _bjobs() -> list[str]:
  try:
    out = subprocess.check_output(
      ["bjobs", "-noheader"], stderr=subprocess.DEVNULL, text=True
    )
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    return lines
  except Exception:
    return []


def _stage(label: str, done: bool, detail: str = "") -> str:
  icon = "✓" if done else "…"
  return f"  {icon} {label:<22} {detail}"


# ── main ──────────────────────────────────────────────────────────────

def main() -> None:
  now = datetime.now().strftime("%Y-%m-%d %H:%M")
  print(f"\nE07 Pipeline  ──  {now}")
  print("─" * 48)

  # stage 1: track finding
  n_chunks = _count("chunk_*.parquet")
  track_done = n_chunks >= N_CHUNKS
  track_detail = _bar(n_chunks, N_CHUNKS) if not track_done else ""
  merged = RESULTS / "merged.parquet"
  if track_done and merged.exists():
    track_detail = f"{_parquet_rows(merged)} tracks"
  print(_stage("[1] Track chunks", track_done, track_detail))

  if not track_done:
    print(_stage("    merged.parquet", False, "waiting for chunks"))
  else:
    print(_stage("    merged.parquet", merged.exists(),
                 _parquet_rows(merged) + " rows" if merged.exists() else "not yet"))

  print()

  # stage 2: vertex finding — detect latest version dir
  vertex_dirs = sorted(RESULTS.glob("vertex_chunks*"), reverse=True)
  if vertex_dirs:
    vdir = vertex_dirs[0]
    n_vchunks = _count(f"{vdir.name}/vertex_*.parquet")
    v_done = n_vchunks >= N_CHUNKS
    v_detail = _bar(n_vchunks, N_CHUNKS) if not v_done else f"{n_vchunks}/{N_CHUNKS}"
    print(_stage(f"[2] {vdir.name}/", v_done, v_detail))
  else:
    print(_stage("[2] Vertex chunks", False, "not started"))

  merged_verts = sorted(RESULTS.glob("vertices_merged*.parquet"), reverse=True)
  if merged_verts:
    mv = merged_verts[0]
    print(_stage(f"    {mv.name}", True,
                 _parquet_rows(mv) + " vertices"))
  else:
    print(_stage("    vertices_merged.parquet", False, "not yet"))

  print()

  # stage 3: maps / crops
  has_map   = bool(list(RESULTS.glob("vertex_map*.png")))
  has_crops = bool(list(RESULTS.glob("vertex_crops*/")))
  print(_stage("[3] Vertex map", has_map))
  print(_stage("    Vertex crops", has_crops))

  print()
  print("─" * 48)

  # KEKCC jobs
  jobs = _bjobs()
  if not jobs:
    print("  KEKCC: no running jobs")
  else:
    print(f"  KEKCC: {len(jobs)} job(s) running")
    for j in jobs[:6]:
      parts = j.split()
      if len(parts) >= 4:
        jid, user, stat, queue = parts[0], parts[1], parts[2], parts[3]
        name = parts[6] if len(parts) > 6 else ""
        print(f"    {jid:>10}  {stat:<5}  {name}")
      else:
        print(f"    {j[:60]}")
    if len(jobs) > 6:
      print(f"    … and {len(jobs)-6} more")

  print()


if __name__ == "__main__":
  main()
