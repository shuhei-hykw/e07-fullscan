"""pytest configuration: skip slow tests unless -m slow is passed."""
import pytest


def pytest_collection_modifyitems(config, items):
  if config.option.markexpr == "slow":
    return  # explicit -m slow: run everything collected
  skip_slow = pytest.mark.skip(reason="slow test: run with pytest -m slow")
  for item in items:
    if item.get_closest_marker("slow"):
      item.add_marker(skip_slow)
