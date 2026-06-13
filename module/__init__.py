"""E07 fullscan — preprocessing core (steps 1-5).

Core pipeline:
  SpngReader -> zpj() -> preprocess() -> binary np.ndarray

Graph-analysis output connection:
  from module.reader import SpngReader
  from module.preprocess import zpj, preprocess
  binary = preprocess(zpj(SpngReader("tile.json")))
"""
from module.reader import ImageEntry, ImageType, SpngReader, load_spng
from module.preprocess import (
  zpj,
  fog_remove,
  otsu_binarize,
  remove_noise,
  preprocess,
)

__all__ = [
  "ImageEntry", "ImageType", "SpngReader", "load_spng",
  "zpj", "fog_remove", "otsu_binarize", "remove_noise", "preprocess",
]
