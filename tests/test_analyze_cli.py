import subprocess
import sys
import tempfile
from pathlib import Path


def _run(*args, **kwargs):
  return subprocess.run(
    [sys.executable, "-m", "module.pipeline", *args],
    capture_output=True, text=True, **kwargs,
  )


def test_help_exits_zero():
  result = _run("--help")
  assert result.returncode == 0


def test_help_mentions_program_name():
  result = _run("--help")
  assert "e07analyze" in result.stdout


def test_no_args_exits_nonzero():
  result = _run()
  assert result.returncode != 0


def test_empty_dir_exits_nonzero():
  with tempfile.TemporaryDirectory() as d:
    result = _run(d)
    assert result.returncode != 0
    assert "No JSON files found" in result.stderr
