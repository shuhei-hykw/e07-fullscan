"""Where the array-heavy helpers run: a CUDA GPU when one is usable.

E07_DEVICE overrides the choice: "cpu" forces numpy, any torch device
string ("cuda", "cuda:1") forces that device. Without it, CUDA is used
when torch is installed and sees a GPU, and numpy otherwise -- so the
same code runs on e07-srv and on kekcc, which has neither.

Only gathers and integer reductions go through torch here; no autograd
is involved, so importing torch next to OpenCV is safe (the deadlock
noted in e07-ml-binary-segmentation is in training's backward pass).
"""
from __future__ import annotations

import functools
import os

_CPU = "cpu"


@functools.cache
def default_device() -> str | None:
  """A torch device string, or None for the numpy path."""
  env = os.environ.get("E07_DEVICE", "").strip()
  if env == _CPU:
    return None
  if env:
    return env
  try:
    import torch
  except ImportError:
    return None
  return "cuda" if torch.cuda.is_available() else None
