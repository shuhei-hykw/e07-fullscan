import argparse
from pathlib import Path
import webbrowser

from e07fullscan.server.app import run


def main() -> None:
  parser = argparse.ArgumentParser(
    prog="e07view",
    description="Launch the E07 full-scan web viewer.",
  )
  parser.add_argument(
    "root_dir", nargs="?", default=".",
    metavar="DIR",
    help="Root directory to browse (default: current directory)",
  )
  parser.add_argument(
    "--host", default="localhost",
    help="Host to bind (default: localhost)",
  )
  parser.add_argument(
    "--port", type=int, default=8000,
    help="Port to listen on (default: 8000)",
  )
  parser.add_argument(
    "--open", action="store_true",
    help="Open browser automatically",
  )
  parser.add_argument(
    "--start", default="",
    metavar="SUBPATH",
    help="Initial sub-path to open",
  )
  parser.add_argument(
    "--results", default=None, metavar="FILE",
    help=(
      "Analysis results file (.db or .parquet) to "
      "enable the results viewer at /results/"
    ),
  )
  args = parser.parse_args()

  results = None
  if args.results:
    from e07fullscan.server.results import ResultsStore
    results = ResultsStore(Path(args.results))
    print(f"Results loaded from {args.results!r}")

  url = f"http://{args.host}:{args.port}"
  print(f"Serving {args.root_dir!r} at {url}")
  if args.results:
    print(f"Results viewer: {url}/results/")
  if args.open:
    webbrowser.open(url)

  run(args.root_dir, host=args.host, port=args.port,
    start_path=args.start, results=results)


if __name__ == "__main__":
  main()
