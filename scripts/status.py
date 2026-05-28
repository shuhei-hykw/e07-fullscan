"""E07 pipeline status monitor.

Usage:
  python scripts/status.py            # single snapshot
  python scripts/status.py --loop     # refresh every 60 s
  python scripts/status.py --loop 30  # refresh every 30 s
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

N_VIEWS  = 2025
N_CHUNKS = 135


# ── helpers ───────────────────────────────────────────────────────────

def _nrows(path: Path) -> int:
  """Return row count of a parquet file (-1 on error)."""
  try:
    import pyarrow.parquet as pq
    return pq.read_metadata(path).num_rows
  except Exception:
    return -1


def _bar(done: int, total: int, width: int = 20) -> str:
  pct  = done / max(total, 1)
  fill = int(width * pct)
  return f"[{'█'*fill}{'░'*(width-fill)}] {done}/{total} ({100*pct:.0f}%)"


def _rows_str(path: Path) -> str:
  n = _nrows(path)
  return f"{n:,}" if n >= 0 else "?"


def _bjobs() -> list[dict]:
  """Return list of all recent LSF jobs (including DONE) as dicts."""
  try:
    out = subprocess.check_output(
      ["bjobs", "-noheader", "-a", "-w"],
      stderr=subprocess.DEVNULL, text=True
    )
    jobs = []
    for line in out.strip().splitlines():
      parts = line.split()
      if len(parts) >= 7:
        jobs.append({
          "id":   parts[0].split("[")[0],
          "stat": parts[2],
          "name": parts[6].split("[")[0],
        })
    return jobs
  except Exception:
    return []


def _tick(ok: bool) -> str:
  return "✓" if ok else "·"


def _section(title: str) -> None:
  print(f"\n  ── {title} {'─'*(44-len(title))}")


# ── pipeline block ────────────────────────────────────────────────────

def _show_pipeline(label: str, chunks_dir: Path, version: str) -> None:
  """Show one complete pipeline (tracking → pairs)."""

  # Step 1: chunks
  n_chunks = len(list(chunks_dir.glob("chunk_*.parquet")))
  chunk_ok  = n_chunks >= N_CHUNKS
  merged    = RESULTS / f"merged_{version}.parquet"
  if version == "v5":
    merged = RESULTS / "merged.parquet"

  print(f"\n  [{label}]")

  # tracking
  if chunk_ok:
    print(f"    {_tick(True)}  tracking     {n_chunks}/{N_CHUNKS} chunks")
  else:
    print(f"    {_tick(False)}  tracking     {_bar(n_chunks, N_CHUNKS)}")

  # merge tracks
  print(f"    {_tick(merged.exists())}  merge tracks "
        + (_rows_str(merged) + " tracks" if merged.exists() else ""))

  # vertex chunks
  vdir   = RESULTS / f"vertex_chunks_{version}"
  n_vc   = len(list(vdir.glob("vertex_*.parquet"))) if vdir.exists() else 0
  verts  = RESULTS / f"vertices_{version}.parquet"
  mvert  = RESULTS / f"vertices_merged_{version}.parquet"

  if chunk_ok:
    if n_vc >= N_CHUNKS:
      print(f"    {_tick(True)}  vertices     {n_vc}/{N_CHUNKS} chunks")
    else:
      print(f"    {_tick(False)}  vertices     {_bar(n_vc, N_CHUNKS)}"
            if n_vc else f"    {_tick(False)}  vertices     not started")
    print(f"    {_tick(mvert.exists())}  merge verts  "
          + (_rows_str(mvert) + " vertices" if mvert.exists() else ""))

  # pairs — find latest base pair file for this version
  if mvert.exists():
    # intra-view: vertex_pairs_{version}*.parquet or vertex_pairs_v??.parquet
    # xview:      vertex_pairs_xview_{version}*.parquet
    # For v5, pairs may be named v6/v7 (iteration counter independent of
    # vertex version); scan for the largest-numbered base file.
    def _latest_pairs(glob_pat: str) -> "Path | None":
      hits = [p for p in sorted(RESULTS.glob(glob_pat))
              if not any(s in p.stem for s in
                         ("filtered", "connected", "strong", "tier", "conn",
                          "golden", "ann", "prefilter"))]
      return hits[-1] if hits else None

    intra = _latest_pairs(f"vertex_pairs_v*.parquet") if version == "v5" \
            else _latest_pairs(f"vertex_pairs_{version}*.parquet")
    xview = _latest_pairs("vertex_pairs_xview_v*.parquet") if version == "v5" \
            else _latest_pairs(f"vertex_pairs_xview_{version}*.parquet")

    for pfile, label2 in [(intra, "pairs intra"), (xview, "pairs xview")]:
      if pfile:
        print(f"    {_tick(True)}  {label2:<12} {_rows_str(pfile):>12}"
              f"  ({pfile.name})")
      else:
        print(f"    {_tick(False)}  {label2:<12}")


# ── candidate catalog ─────────────────────────────────────────────────

def _show_candidates() -> None:
  _section("Candidate catalog")

  files = [
    ("vertex_pairs_v7_filtered.parquet",       "v7 filtered  (intra)"),
    ("vertex_pairs_v7_strong_ann.parquet",      "v7 strong    (intra)"),
    ("vertex_pairs_v7_tier_a.parquet",          "v7 Tier A    (intra)"),
    ("vertex_pairs_xview_v1_conn_ll.parquet",   "xview conn   (ΛΛ range)"),
    ("vertex_pairs_xview_v1_strong.parquet",    "xview strong"),
  ]
  for fname, desc in files:
    p = RESULTS / fname
    if p.exists():
      print(f"    {_tick(True)}  {desc:<26} {_rows_str(p):>8} pairs")


# ── crops ─────────────────────────────────────────────────────────────

def _show_crops() -> None:
  crop_dirs = sorted(
    d for d in list(RESULTS.glob("pair_crops_*"))
             + list(RESULTS.glob("vertex_crops_*"))
    if d.is_dir()
  )
  if not crop_dirs:
    return
  _section("Crop images")
  for d in crop_dirs:
    n = len(list(d.glob("*.png")))
    # check if crop_vertices.py is still writing to this dir
    meta = d / "run_params.json"
    target = None
    if meta.exists():
      import json as _json
      try:
        p = _json.loads(meta.read_text())
        target = int(p.get("n_samples") or p.get("n-samples") or 0)
      except Exception:
        pass
    if target and n < target:
      bar = _bar(n, target, width=14)
      print(f"    {_tick(False)}  {d.name:<30} {bar} (generating)")
    else:
      print(f"    {_tick(n>0)}  {d.name:<30} {n} images")


# ── KEKCC ─────────────────────────────────────────────────────────────

def _show_kekcc() -> None:
  _section("KEKCC jobs")
  jobs = _bjobs()
  if not jobs:
    print("    (no running jobs)")
    return

  # group by job name
  from collections import Counter
  by_name: dict[str, Counter] = {}
  for j in jobs:
    name = j["name"].split("[")[0]  # strip array index
    if name not in by_name:
      by_name[name] = Counter()
    by_name[name][j["stat"]] += 1

  for name, stats in sorted(by_name.items()):
    total  = sum(stats.values())
    run    = stats.get("RUN", 0)
    pend   = stats.get("PEND", 0)
    done   = stats.get("DONE", 0)
    parts  = []
    if run:   parts.append(f"RUN={run}")
    if pend:  parts.append(f"PEND={pend}")
    if done:  parts.append(f"DONE={done}")
    print(f"    {_tick(run>0)}  {name:<16} {total:>4} jobs  {' '.join(parts)}")


# ── main ──────────────────────────────────────────────────────────────

def _next_step() -> str:
  """Return a hint for the next manual pipeline step."""
  n_v6   = len(list((RESULTS / "chunks_v6").glob("chunk_*.parquet")))
  n_vc6  = len(list((RESULTS / "vertex_chunks_v6").glob("vertex_*.parquet")))
  merged = RESULTS / "merged_v6.parquet"
  verts  = RESULTS / "vertices_v6.parquet"
  mvert  = RESULTS / "vertices_merged_v6.parquet"
  pairs  = RESULTS / "vertex_pairs_v6.parquet"

  if n_v6 < N_CHUNKS:
    return "wait: tracking"
  if not merged.exists():
    return "run: merge_chunks.py --input results/chunks_v6"
  if n_vc6 < N_CHUNKS:
    return "wait: vertex finding"
  if not verts.exists():
    return "run: merge_chunks.py --input results/vertex_chunks_v6"
  if not mvert.exists():
    return "run: merge_vertices.py"
  xview  = RESULTS / "vertex_pairs_xview_v6.parquet"
  xconn  = RESULTS / "vertex_pairs_xview_v6_conn.parquet"

  if not pairs.exists():
    return "run: find_pairs.py"
  if not xview.exists():
    return "run: find_crossview_pairs.py"
  if not xconn.exists():
    return "run: filter_xview_pairs.py (in progress)"
  return "v6 pipeline complete"


def _display() -> None:
  now  = datetime.now().strftime("%H:%M:%S")
  jobs = _bjobs()

  # aggregate by job name
  by_name: dict[str, dict] = {}
  for j in jobs:
    nm = j["name"]
    if nm not in by_name:
      by_name[nm] = {"id": j["id"], "run": 0, "pend": 0, "done": 0}
    by_name[nm]["run"]  += j["stat"] == "RUN"
    by_name[nm]["pend"] += j["stat"] == "PEND"
    by_name[nm]["done"] += j["stat"] == "DONE"

  LOG_DIR = ROOT / "logs" / "kekcc"

  # output file counts (chunk/slice-based jobs)
  _out_count = {
    "e07v6":     len(list(
      (RESULTS / "chunks_v6").glob("chunk_*.parquet"))),
    "e07vertex": len(list(
      (RESULTS / "vertex_chunks_v6").glob("vertex_*.parquet"))),
    "e07intra":  len(list(
      (RESULTS / "intra_filter_slices").glob("slice_*.parquet"))),
    "e07xconn":  len(list(
      (RESULTS / "xconn_filter_slices").glob("slice_*.parquet"))),
  }

  # log-based progress strings (single-job filter tasks)
  def _log_progress(log_path: Path, total: int = 0) -> str:
    if not log_path.exists():
      return ""
    try:
      lines_raw = log_path.read_text(errors="replace").splitlines()
    except Exception:
      return ""
    # find last "N/M …" line
    for ln in reversed(lines_raw):
      import re as _re
      m = _re.search(r"(\d+)/(\d+)", ln)
      if m:
        done, tot = int(m.group(1)), int(m.group(2))
        pct = 100 * done / max(tot, 1)
        return f"  {_bar(done, tot, width=14)}"
    # fallback: last non-empty line
    for ln in reversed(lines_raw):
      ln = ln.strip()
      if ln:
        return f"  {ln[:40]}"
    return ""

  _log_progress_map = {
    "e07intra": _log_progress(LOG_DIR / "intra_filter.log"),
    "e07xconn": _log_progress(LOG_DIR / "xconn_filter.log"),
  }

  lines = []
  for nm, s in by_name.items():
    total   = s["run"] + s["pend"] + s["done"]
    out_n   = _out_count.get(nm, 0)
    prog    = _log_progress_map.get(nm, "")
    # for array jobs show chunk progress bar; for single jobs show log progress
    if total > 1:
      bar     = _bar(s["done"], total, width=12)
      out_str = f"  out={out_n}/{total}" if out_n else ""
      suffix  = f"{out_str}  {bar}"
    else:
      suffix  = prog if prog else ""
    lines.append(
      f"  #{s['id']}  {nm:<12}"
      f"  RUN={s['run']:>3} PEND={s['pend']:>3} DONE={s['done']:>3}/{total}"
      f"{suffix}"
    )

  nxt = _next_step()
  active = any(s["run"] + s["pend"] > 0 for s in by_name.values())

  print(f"[{now}]  {'running' if active else 'idle'}  →  {nxt}")
  for ln in lines:
    print(ln)

  _section("Pipeline")
  _show_pipeline("v6", RESULTS / "chunks_v6", "v6")
  _show_candidates()
  _show_crops()


def main() -> None:
  args     = sys.argv[1:]
  loop     = "--loop" in args
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
