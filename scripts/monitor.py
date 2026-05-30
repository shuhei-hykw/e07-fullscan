#!/usr/bin/env python
"""Live monitor for module analysis. Run in a separate tmux pane.

Local mode (single process):
  python scripts/monitor.py --log analyze.log --output out.parquet

Batch mode (LSF array job):
  python scripts/monitor.py --job-name e07test2 --log-dir logs/kekcc \
      --out-dir test_results --total 2025
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_REFRESH = 5.0

_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_RED    = "\033[31m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"
_DIM    = "\033[2m"

_LOG_PATTERN = re.compile(r"\.json: (\d+) tracks")
_EOL = "\033[K"

# ── rendering ──────────────────────────────────────────────────────────

def _render(lines: list[str], prev_n: int) -> int:
    buf = []
    if prev_n:
        buf.append(f"\033[{prev_n}A\r")
    for ln in lines:
        buf.append(ln + _EOL + "\n")
    sys.stdout.write("".join(buf))
    sys.stdout.flush()
    return len(lines)

# ── helpers ────────────────────────────────────────────────────────────

def _fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _bar(pct: float, width: int = 30) -> str:
    filled = int(width * min(pct, 100) / 100)
    return "█" * filled + "░" * (width - filled)


def _row(label: str, value: str, color: str = "", pad: int = 20) -> str:
    return f"│  {label:<{pad}}{color}{value}{_RESET}"


def _divider(w: int, left: str = "├", right: str = "┤") -> str:
    return f"{left}{'─' * w}{right}"


def _count_log(log_path: Path) -> tuple[int, int]:
    """Count (views_done, tracks) from a single verbose log file."""
    if not log_path.exists():
        return 0, 0
    views = tracks = 0
    for ln in log_path.read_text(errors="replace").splitlines():
        m = _LOG_PATTERN.search(ln)
        if m:
            views += 1
            tracks += int(m.group(1))
    return views, tracks


def _file_stat(path: Path) -> tuple[float, str]:
    try:
        st = path.stat()
        return st.st_size / 1048576, time.strftime(
            "%H:%M:%S", time.localtime(st.st_mtime)
        )
    except FileNotFoundError:
        return 0.0, "---"

# ── local process helpers ──────────────────────────────────────────────

def _find_analyze_pid() -> int | None:
    try:
        out = subprocess.check_output(
            ["pgrep", "-u", os.environ.get("USER", ""),
             "-f", "module.analyze"],
            text=True, stderr=subprocess.DEVNULL,
        )
        pids = [int(p) for p in out.strip().splitlines() if p]
        return pids[0] if pids else None
    except Exception:
        return None


def _read_proc(pid: int) -> tuple[float, float]:
    """Return (mem_mb, elapsed_s)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        clk  = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        uptime_s   = float(Path("/proc/uptime").read_text().split()[0])
        boot_time  = time.time() - uptime_s
        elapsed_s  = time.time() - (boot_time + int(stat[21]) / clk)
        mem_kb = int(
            Path(f"/proc/{pid}/status").read_text()
            .split("VmRSS:")[1].split()[0]
        )
        return mem_kb / 1024.0, elapsed_s
    except Exception:
        return 0.0, 0.0


def _instant_cpu(pid: int, interval: float = 0.25) -> float:
    try:
        clk = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        def _t():
            s = Path(f"/proc/{pid}/stat").read_text().split()
            return int(s[13]) + int(s[14])
        t0 = _t(); w0 = time.time()
        time.sleep(interval)
        t1 = _t(); w1 = time.time()
        return (t1 - t0) / clk / (w1 - w0) * 100.0
    except Exception:
        return 0.0

# ── LSF helpers ────────────────────────────────────────────────────────

_STAT_COLOR = {
    "RUN":  _GREEN,
    "DONE": _CYAN,
    "EXIT": _RED,
    "PEND": _YELLOW,
}


def _bjobs(job_name: str) -> tuple[list[dict], str, str]:
    """Query bjobs for an array job.

    Returns (jobs, job_id, queue) where jobs is a list of dicts with
    keys: idx, stat, host, queue.
    """
    try:
        out = subprocess.check_output(
            ["bjobs", "-noheader", "-J", job_name],
            text=True, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return [], "---", "---"

    jobs = []
    job_id = "---"
    queue  = "---"
    for ln in out.strip().splitlines():
        parts = ln.split()
        if len(parts) < 7:
            continue
        job_id = parts[0]
        stat   = parts[2]
        queue  = parts[3]
        host   = re.sub(r"^\d+\*", "", parts[5]) if parts[5] != "-" else "---"
        name   = parts[6]
        m = re.search(r"\[(\d+)\]", name)
        idx = int(m.group(1)) if m else 0
        jobs.append({"idx": idx, "stat": stat, "host": host, "queue": queue})
    return sorted(jobs, key=lambda x: x["idx"]), job_id, queue

# ── frame builders ─────────────────────────────────────────────────────

def _build_local(args, W: int) -> list[str]:
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    pid = _find_analyze_pid()
    if pid:
        cpu_pct = _instant_cpu(pid, interval=min(0.25, args.refresh / 8))
        mem_mb, elapsed_s = _read_proc(pid)
        p_color, p_status = _GREEN, f"PID {pid}  running"
    else:
        cpu_pct = mem_mb = elapsed_s = 0.0
        p_color, p_status = _YELLOW, "not found / finished"

    done, n_tracks = _count_log(args.log) if args.log else (0, 0)
    total = args.total
    pct   = done / total * 100.0 if total > 0 else 0.0
    eta_s = (elapsed_s / (pct / 100) - elapsed_s
             if 0 < pct < 100 and elapsed_s > 0 else 0.0)
    fsize_mb, fmtime = _file_stat(args.output) if args.output else (0.0, "---")

    L: list[str] = []
    a = L.append

    a(f"┌{'─' * W}┐")
    title = "  E07 fullscan — local monitor"
    a(f"│{_BOLD}{title}{_RESET}{' ' * (W - len(title))}│")
    a(f"│  {_DIM}{now_str}{_RESET}{' ' * (W - len(now_str) - 2)}│")

    a(_divider(W))
    a(_row("Process", p_status, p_color))
    if pid:
        a(_row("CPU", f"{cpu_pct:5.1f}%", _GREEN if cpu_pct > 20 else _DIM))
        a(_row("Memory",  f"{mem_mb:,.0f} MB"))
        a(_row("Elapsed", _fmt_time(elapsed_s)))
    else:
        a(_row("", "")); a(_row("", "")); a(_row("", ""))

    a(_divider(W))
    if args.log:
        a(_row("Views done",   f"{done:,} / {total:,}", _CYAN))
        a(_row("Tracks found", f"{n_tracks:,}"))
        a(f"│  [{_bar(pct, 30)}] {pct:5.1f}%")
        a(_row("ETA", _fmt_time(eta_s) if eta_s > 0 else "---", _YELLOW))
    else:
        a(_row("Progress", "--log not specified", _DIM))
        a(_row("", "")); a(_row("", "")); a(_row("", ""))

    a(_divider(W))
    if args.output:
        out_name = str(args.output)
        if len(out_name) > W - 24:
            out_name = "…" + out_name[-(W - 25):]
        a(_row("Output", out_name, _CYAN if fsize_mb > 0 else _DIM))
        if fsize_mb > 0:
            a(_row("Size",       f"{fsize_mb:.2f} MB"))
            a(_row("Last write", fmtime))
        else:
            a(_row("Size", "not written yet", _DIM)); a(_row("", ""))
    else:
        a(_row("", "")); a(_row("", "")); a(_row("", ""))

    a(f"└{'─' * W}┘")
    a(f"  {_DIM}Ctrl-C to quit   refresh {args.refresh:.0f}s{_RESET}")
    return L


def _build_batch(args, W: int) -> list[str]:
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    # --- LSF job status ---
    jobs, job_id, queue = _bjobs(args.job_name)
    counts: dict[str, int] = {"PEND": 0, "RUN": 0, "DONE": 0, "EXIT": 0}
    for j in jobs:
        counts[j["stat"]] = counts.get(j["stat"], 0) + 1
    n_jobs = len(jobs)

    # --- progress from all log files ---
    log_dir = Path(args.log_dir) if args.log_dir else None
    total_done = total_tracks = 0
    n_logs = 0
    if log_dir and log_dir.exists():
        for lf in sorted(log_dir.glob("analyze_*.log")):
            v, t = _count_log(lf)
            total_done   += v
            total_tracks += t
            if v > 0:
                n_logs += 1

    total = args.total
    pct   = total_done / total * 100.0 if total > 0 else 0.0

    # ETA: use oldest running job's elapsed time as proxy
    # (approximate: assume uniform progress across all jobs)
    elapsed_approx = 0.0
    if log_dir and log_dir.exists():
        logs = sorted(log_dir.glob("analyze_*.log"))
        if logs:
            oldest = min(logs, key=lambda p: p.stat().st_mtime
                         if p.exists() else float("inf"))
            try:
                elapsed_approx = time.time() - oldest.stat().st_mtime + \
                    oldest.stat().st_size / 1  # rough proxy
            except Exception:
                pass
    # simpler ETA: just use wall-clock since first log appeared
    eta_s = 0.0
    if log_dir and log_dir.exists():
        logs = list(log_dir.glob("analyze_*.log"))
        if logs and 0 < pct < 100:
            try:
                first_mtime = min(p.stat().st_mtime for p in logs)
                elapsed_approx = time.time() - first_mtime
                eta_s = elapsed_approx / (pct / 100) - elapsed_approx
            except Exception:
                pass

    # --- output chunks ---
    out_dir = Path(args.out_dir) if args.out_dir else None
    chunks_done = 0
    total_mb = 0.0
    if out_dir and out_dir.exists():
        parquets = list(out_dir.glob(args.file_pattern))
        chunks_done = len(parquets)
        total_mb = sum(p.stat().st_size for p in parquets) / 1048576

    L: list[str] = []
    a = L.append

    a(f"┌{'─' * W}┐")
    title = "  E07 fullscan — batch monitor (LSF)"
    a(f"│{_BOLD}{title}{_RESET}{' ' * (W - len(title))}│")
    a(f"│  {_DIM}{now_str}{_RESET}{' ' * (W - len(now_str) - 2)}│")

    # --- job summary ---
    a(_divider(W))
    a(_row("Job name", args.job_name, _CYAN))
    a(_row("Job ID",   job_id, _DIM))
    a(_row("Queue",    queue))
    n_run  = counts["RUN"]
    n_pend = counts["PEND"]
    n_done = counts["DONE"]
    n_exit = counts["EXIT"]
    stat_str = (
        f"{_GREEN}RUN {n_run:>3}{_RESET}  "
        f"{_YELLOW}PEND {n_pend:>3}{_RESET}  "
        f"{_CYAN}DONE {n_done:>3}{_RESET}  "
        f"{_RED}EXIT {n_exit:>3}{_RESET}"
    )
    a(f"│  {stat_str}")

    # --- per-job list (up to 10) ---
    a(_divider(W))
    show = jobs[:10]
    for j in show:
        sc = _STAT_COLOR.get(j["stat"], "")
        idx_s  = f"[{j['idx']:>2}]"
        stat_s = f"{sc}{j['stat']:<4}{_RESET}"
        host_s = j["host"][:16]
        a(f"│  {idx_s} {stat_s}  {host_s}")
    # pad to fixed height (max 10 rows)
    for _ in range(10 - len(show)):
        a("│")

    # --- overall progress ---
    a(_divider(W))
    a(_row("Views done",   f"{total_done:,} / {total:,}", _CYAN))
    a(_row("Tracks found", f"{total_tracks:,}"))
    a(f"│  [{_bar(pct, 30)}] {pct:5.1f}%")
    a(_row("ETA", _fmt_time(eta_s) if eta_s > 0 else "---", _YELLOW))
    a(_row("Logs reporting", f"{n_logs} / {n_jobs}"))

    # --- output files ---
    a(_divider(W))
    a(_row("Chunks written",
           f"{chunks_done} / {n_jobs}",
           _GREEN if chunks_done == n_jobs > 0 else _CYAN))
    if total_mb > 0:
        a(_row("Total size", f"{total_mb:.1f} MB"))
    else:
        a(_row("Total size", "not written yet", _DIM))
    if chunks_done == n_jobs > 0:
        a(_row("→ merge with",
               "scripts/merge_chunks.py", _DIM))
    else:
        a(_row("", ""))

    a(f"└{'─' * W}┘")
    a(f"  {_DIM}Ctrl-C to quit   refresh {args.refresh:.0f}s{_RESET}")
    return L

# ── main ───────────────────────────────────────────────────────────────

def _build_compact(args, W: int) -> list[str]:
    """Compact single-pane view for small terminal windows."""
    now_str = time.strftime("%H:%M:%S")
    L: list[str] = []
    a = L.append

    if args.job_name:
        jobs, job_id, queue = _bjobs(args.job_name)
        counts: dict[str, int] = {"PEND": 0, "RUN": 0, "DONE": 0, "EXIT": 0}
        for j in jobs:
            counts[j["stat"]] = counts.get(j["stat"], 0) + 1
        n_jobs = len(jobs)

        log_dir = Path(args.log_dir) if args.log_dir else None
        total_done = total_tracks = 0
        if log_dir and log_dir.exists():
            for lf in sorted(log_dir.glob("analyze_*.log")):
                v, t = _count_log(lf)
                total_done += v; total_tracks += t

        total = args.total
        pct = total_done / total * 100.0 if total > 0 else 0.0

        out_dir = Path(args.out_dir) if args.out_dir else None
        chunks_done = 0
        if out_dir and out_dir.exists():
            chunks_done = len(list(out_dir.glob(args.file_pattern)))

        stat_str = (
            f"{_GREEN}R{counts['RUN']}{_RESET}"
            f" {_YELLOW}P{counts['PEND']}{_RESET}"
            f" {_CYAN}D{counts['DONE']}{_RESET}"
            f" {_RED}X{counts['EXIT']}{_RESET}"
        )
        a(f"┌{'─'*W}┐")
        a(f"│ {_BOLD}{args.job_name}{_RESET}"
          f"  {_DIM}{now_str}{_RESET}"
          f"{' '*(W - len(args.job_name) - 10)}│")
        a(f"│ {stat_str}  {_DIM}q={queue}{_RESET}"
          f"{' '*(W - 28)}│")
        a(f"│ [{_bar(pct, W-10)}] {pct:4.1f}%│")
        a(f"│ {_CYAN}{total_done:,}/{total:,} views"
          f"  chunks {chunks_done}/{n_jobs}{_RESET}"
          f"{' '*(W - len(f'{total_done:,}/{total:,} views  chunks {chunks_done}/{n_jobs}') - 2)}│")
        a(f"└{'─'*W}┘")
    else:
        pid = _find_analyze_pid()
        if pid:
            mem_mb, elapsed_s = _read_proc(pid)
            status = f"PID {pid}  {_fmt_time(elapsed_s)}  {mem_mb:.0f}MB"
            color  = _GREEN
        else:
            status, color = "not running", _YELLOW
            elapsed_s = 0.0

        done, n_tracks = _count_log(args.log) if args.log else (0, 0)
        pct = done / args.total * 100.0 if args.total > 0 else 0.0

        a(f"┌{'─'*W}┐")
        a(f"│ {color}{status}{_RESET}"
          f"  {_DIM}{now_str}{_RESET}"
          f"{' '*(W - len(status) - 10)}│")
        a(f"│ [{_bar(pct, W-10)}] {pct:4.1f}%│")
        a(f"│ {_CYAN}{done:,}/{args.total:,} views"
          f"  {n_tracks:,} tracks{_RESET}"
          f"{' '*(W - len(f'{done:,}/{args.total:,} views  {n_tracks:,} tracks') - 2)}│")
        a(f"└{'─'*W}┘")

    return L


def main() -> None:
    ap = argparse.ArgumentParser(description="E07 analysis monitor")

    # pipeline-overview mode (was scripts/status.py)
    ap.add_argument("--pipeline", action="store_true",
                    help="Pipeline overview + next step (snapshot; --loop N "
                         "to refresh). Default when no job/local flags given.")

    # local mode
    ap.add_argument("--log",     type=Path, default=None,
                    help="Stderr log file (local mode)")
    ap.add_argument("--output",  type=Path, default=None,
                    help="Output parquet path (local mode)")

    # batch mode
    ap.add_argument("--job-name", default=None,
                    help="LSF job name to monitor (batch mode)")
    ap.add_argument("--log-dir",  default="logs/kekcc",
                    help="Directory containing analyze_NNNN.log files")
    ap.add_argument("--out-dir",  default="test_results",
                    help="Directory containing output parquet files")
    ap.add_argument("--file-pattern", default="chunk_*.parquet",
                    help="Glob pattern for output parquets "
                         "(default: chunk_*.parquet; "
                         "use vertex_*.parquet for vertex jobs)")

    # common
    ap.add_argument("--total",   type=int, default=2025,
                    help="Total number of JSON views")
    ap.add_argument("--refresh", type=float, default=_REFRESH,
                    help="Refresh interval in seconds")
    ap.add_argument("--compact", action="store_true",
                    help="Compact 4-line display for small windows")
    ap.add_argument("--width",   type=int, default=None,
                    help="Display width in chars (default: 38 compact, 54 full)")
    ap.add_argument("--loop",    type=int, default=None,
                    help="Pipeline mode: refresh every N seconds")
    args = ap.parse_args()

    # pipeline-overview mode: explicit --pipeline, or no live-job flags given.
    live_flags = (args.log is not None or args.output is not None
                  or args.job_name is not None)
    if args.pipeline or not live_flags:
        from module.pipeline_status import run as _pipeline_run
        _pipeline_run(loop=args.loop)
        return

    batch_mode = args.job_name is not None
    if args.compact:
        W = args.width or 38
    else:
        W = args.width or 54
    prev_n = 0

    while True:
        try:
            if args.compact:
                L = _build_compact(args, W)
            elif batch_mode:
                L = _build_batch(args, W)
            else:
                L = _build_local(args, W)
            prev_n = _render(L, prev_n)
        except Exception as e:
            sys.stderr.write(f"render error: {e}\n")

        try:
            time.sleep(args.refresh)
        except KeyboardInterrupt:
            print("\nMonitor stopped.")
            break


if __name__ == "__main__":
    main()
