"""Pick the LSF queue that can start the most jobs right now.

KEKCC's queues differ by orders of magnitude in how backed up they
are, and which one is best changes by the hour: on 2026-09-08 queue
`s` had 3,192 of its 3,200 slots busy with 14,132 jobs pending, while
`h` had 89 running and nothing waiting. Hard-coding a queue in the
config therefore ages badly, so `queue: auto` asks at submission time.

Only queues the user may actually submit to are considered -- LSF
already answers that, since `bqueues -u <user>` lists exactly those --
and a queue whose CPU, wall or memory limit cannot hold one job is
dropped before ranking.
"""
from __future__ import annotations

import re
import subprocess

# Columns of the `bqueues` table we rely on.
_HEADER = "QUEUE_NAME"
_UNLIMITED = "-"
# Fraction of a queue's per-user slot limit worth treating as "can
# start now"; LSF hands out slots gradually, so this stays a ranking
# key rather than a promise.
_SLOTS_PER_JOB_MIN = 1


def _run(cmd: list[str]) -> str:
  out = subprocess.run(cmd, capture_output=True, text=True)
  if out.returncode != 0:
    raise RuntimeError(f"{' '.join(cmd)} failed: {out.stderr.strip()}")
  return out.stdout


def _as_int(token: str, default: int) -> int:
  return default if token == _UNLIMITED else int(token)


def list_queues(user: str | None = None) -> list[dict]:
  """Open queues the user may submit to, with their current load."""
  cmd = ["bqueues"]
  if user:
    cmd += ["-u", user]
  rows = []
  for line in _run(cmd).splitlines():
    parts = line.split()
    if not parts or parts[0] == _HEADER or len(parts) < 11:
      continue
    name, _prio, status = parts[0], parts[1], parts[2]
    if not status.startswith("Open"):
      continue
    rows.append({
      "name": name, "status": status,
      "max_slots": _as_int(parts[3], 10 ** 9),
      "user_slots": _as_int(parts[4], 10 ** 9),
      "pending": int(parts[8]), "running": int(parts[9]),
    })
  return rows


def _limits(name: str) -> dict:
  """CPU (min), wall (min) and memory (MB) limits of one queue."""
  text = _run(["bqueues", "-l", name])
  out = {"cpu_min": None, "run_min": None, "mem_mb": None,
         "task_min": 1, "task_max": None}
  cpu = re.search(r"CPULIMIT\s*\n\s*([\d.]+)\s*min", text)
  run = re.search(r"RUNLIMIT\s*\n\s*([\d.]+)\s*min", text)
  mem = re.search(r"MEMLIMIT.*\n\s*([\d.]+)\s*([KMGT])", text)
  if cpu:
    out["cpu_min"] = float(cpu.group(1))
  if run:
    out["run_min"] = float(run.group(1))
  if mem:
    scale = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 ** 2}
    out["mem_mb"] = float(mem.group(1)) * scale[mem.group(2)]
  # TASKLIMIT is "max", "min max" or "min default max". Queue p is
  # "2 4 64" and rejects -n 1 outright ("Too few tasks requested"),
  # which is not something the table view of bqueues shows.
  task = re.search(r"TASKLIMIT\s*\n\s*([\d ]+)", text)
  if task:
    vals = [int(v) for v in task.group(1).split()]
    if len(vals) == 1:
      out["task_max"] = vals[0]
    else:
      out["task_min"], out["task_max"] = vals[0], vals[-1]
  return out


def rank(n_cores: int, mem_mb: int, cpu_min: float, run_min: float,
         user: str | None = None) -> list[dict]:
  """Usable queues, best first.

  Ranked by how many of our jobs could start immediately -- the
  smaller of the per-user slot limit and the queue's free slots,
  divided by the slots one job takes -- and then by how short the
  queue's backlog is. A queue with jobs already waiting will make us
  wait too, however many slots it nominally allows.
  """
  usable = []
  for q in list_queues(user):
    lim = _limits(q["name"])
    if lim["mem_mb"] is not None and lim["mem_mb"] < mem_mb:
      continue
    if lim["cpu_min"] is not None and lim["cpu_min"] < cpu_min:
      continue
    if lim["run_min"] is not None and lim["run_min"] < run_min:
      continue
    if n_cores < lim["task_min"]:
      continue
    if lim["task_max"] is not None and n_cores > lim["task_max"]:
      continue
    free = max(q["max_slots"] - q["running"], 0)
    startable = min(q["user_slots"], free) // max(n_cores, 1)
    if startable < _SLOTS_PER_JOB_MIN:
      continue
    usable.append({**q, **lim, "startable": startable})
  usable.sort(key=lambda q: (-q["startable"], q["pending"], q["name"]))
  # A queue with nothing waiting beats a bigger one with a backlog.
  usable.sort(key=lambda q: (q["pending"] > 0, -q["startable"]))
  return usable


def describe(queues: list[dict]) -> str:
  lines = ["  queue  startable  pending  running  cpu_min  run_min  tasks"]
  for q in queues:
    lines.append(
      f"  {q['name']:<6} {q['startable']:9d} {q['pending']:8d} "
      f"{q['running']:8d} {q['cpu_min'] or 0:8.0f} {q['run_min'] or 0:8.0f}"
      f"  {q['task_min']}-{q['task_max'] or '-'}")
  return "\n".join(lines)


# LSF refuses an array with more elements than MAX_JOB_ARRAY_SIZE, so a
# 2,025-view run has to go in several bsubs.
_DEFAULT_ARRAY_MAX = 1000


def max_array_size(default: int = _DEFAULT_ARRAY_MAX) -> int:
  """MAX_JOB_ARRAY_SIZE from the cluster, or a safe default."""
  try:
    text = _run(["bparams", "-a"])
  except (RuntimeError, OSError):
    return default
  m = re.search(r"MAX_JOB_ARRAY_SIZE\s*=\s*(\d+)", text)
  return int(m.group(1)) if m else default


def split_array(lo: int, hi: int, limit: int) -> list[tuple[int, int]]:
  """Break an inclusive index range into arrays of at most `limit`."""
  return [(a, min(a + limit - 1, hi)) for a in range(lo, hi + 1, limit)]
