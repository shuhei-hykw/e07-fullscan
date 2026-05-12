"""E07 pipeline status monitor.

Usage:
  python scripts/status.py            # single snapshot
  python scripts/status.py --loop     # refresh every 60 s (Ctrl-C to stop)
  python scripts/status.py --loop 30  # refresh every 30 s

For pytest progress, run tests with logging:
  python -m pytest -m slow -v 2>&1 | tee logs/pytest_last.log
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
LOGS    = ROOT / "logs"
PYTEST_LOG = LOGS / "pytest_last.log"

N_CHUNKS = 135


# ── helpers ───────────────────────────────────────────────────────────

def _count(pattern: str) -> int:
  return len(list(RESULTS.glob(pattern)))


def _parquet_rows(path: Path) -> str:
  try:
    import pyarrow.parquet as pq
    return f"{pq.read_metadata(path).num_rows:,}"
  except Exception:
    return "?"


def _bar(done: int, total: int, width: int = 18) -> str:
  filled = int(width * done / max(total, 1))
  return f"[{'█'*filled}{'░'*(width-filled)}] {done}/{total}"


def _bjobs() -> list[str]:
  try:
    out = subprocess.check_output(
      ["bjobs", "-noheader"], stderr=subprocess.DEVNULL, text=True
    )
    return [l.strip() for l in out.strip().splitlines() if l.strip()]
  except Exception:
    return []


def _stage(label: str, done: bool, detail: str = "") -> str:
  return f"  {'✓' if done else '…'} {label:<24} {detail}"


# ── pytest progress ───────────────────────────────────────────────────

def _pytest_status() -> list[str]:
  """Parse logs/pytest_last.log and return summary lines."""
  if not PYTEST_LOG.exists():
    return []

  try:
    text = PYTEST_LOG.read_text(errors="replace")
  except Exception:
    return []

  lines = text.splitlines()
  if not lines:
    return []

  # count passed / failed / error
  passed = text.count(" PASSED")
  failed = text.count(" FAILED")
  error  = text.count(" ERROR")

  # find total collected
  total = 0
  for line in lines:
    m = re.search(r"collected (\d+) items?", line)
    if m:
      total = int(m.group(1))
      break

  # find last test line (most recent progress)
  last_test = ""
  for line in reversed(lines):
    if " PASSED" in line or " FAILED" in line or " ERROR" in line:
      # shorten: just the test name and result
      m = re.search(r"::(test_\S+)\s+(PASSED|FAILED|ERROR)", line)
      if m:
        last_test = f"{m.group(1)} {m.group(2)}"
      break

  # detect if finished
  finished = any("passed" in l or "failed" in l or "error" in l
                 for l in lines[-5:] if l.startswith("="))

  done_count = passed + failed + error
  pct = f"{100*done_count//max(total,1)}%" if total else "?"
  status = "done" if finished else "running"
  bar = _bar(done_count, total) if total else ""

  out = [f"  {'✓' if finished else '…'} pytest  {bar}  "
         f"✓{passed} ✗{failed}  [{status}]"]
  if last_test:
    out.append(f"      last: {last_test}")
  if failed:
    # show failed test names
    for line in lines:
      if " FAILED" in line:
        m = re.search(r"::(test_\S+)\s+FAILED", line)
        if m:
          out.append(f"      FAIL: {m.group(1)}")
  return out


# ── main display ──────────────────────────────────────────────────────

def _display() -> None:
  now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  print(f"\nE07 Pipeline  ──  {now}")
  print("─" * 52)

  # [1] tracks
  n_chunks  = _count("chunk_*.parquet")
  track_done = n_chunks >= N_CHUNKS
  merged    = RESULTS / "merged.parquet"
  if track_done and merged.exists():
    detail = f"{_parquet_rows(merged)} tracks"
  else:
    detail = _bar(n_chunks, N_CHUNKS)
  print(_stage("[1] Track chunks", track_done, detail))
  if track_done:
    print(_stage("    merged.parquet", merged.exists(),
                 _parquet_rows(merged) if merged.exists() else "not yet"))

  print()

  # [2] vertices
  vdirs = sorted(RESULTS.glob("vertex_chunks*"), reverse=True)
  if vdirs:
    vdir = vdirs[0]
    n_vc  = _count(f"{vdir.name}/vertex_*.parquet")
    v_done = n_vc >= N_CHUNKS
    print(_stage(f"[2] {vdir.name}/", v_done,
                 f"{n_vc}/{N_CHUNKS}" if v_done else _bar(n_vc, N_CHUNKS)))
  else:
    print(_stage("[2] Vertex chunks", False, "not started"))

  mverts = sorted(RESULTS.glob("vertices_merged*.parquet"), reverse=True)
  if mverts:
    mv = mverts[0]
    print(_stage(f"    {mv.name}", True, _parquet_rows(mv) + " vertices"))
  else:
    print(_stage("    vertices_merged.parquet", False, "not yet"))

  print()

  # [3] maps / crops
  print(_stage("[3] Vertex map",   bool(list(RESULTS.glob("vertex_map*.png")))))
  print(_stage("    Vertex crops", bool(list(RESULTS.glob("vertex_crops*/")))))

  print()
  print("─" * 52)

  # KEKCC
  jobs = _bjobs()
  if not jobs:
    print("  KEKCC: no running jobs")
  else:
    print(f"  KEKCC: {len(jobs)} job(s)")
    for j in jobs[:5]:
      parts = j.split()
      name = parts[6] if len(parts) > 6 else ""
      stat = parts[2] if len(parts) > 2 else ""
      jid  = parts[0] if parts else ""
      print(f"    {jid:>10}  {stat:<5}  {name}")
    if len(jobs) > 5:
      print(f"    … and {len(jobs)-5} more")

  # pytest
  pt = _pytest_status()
  if pt:
    print()
    for line in pt:
      print(line)

  print()


def main() -> None:
  args = sys.argv[1:]
  loop = "--loop" in args
  interval = 60
  for i, a in enumerate(args):
    if a == "--loop" and i + 1 < len(args):
      try:
        interval = int(args[i + 1])
      except ValueError:
        pass

  if not loop:
    _display()
    return

  try:
    while True:
      os.system("clear")
      _display()
      print(f"  (refreshing every {interval}s — Ctrl-C to stop)")
      time.sleep(interval)
  except KeyboardInterrupt:
    print("\nMonitor stopped.")


if __name__ == "__main__":
  main()
