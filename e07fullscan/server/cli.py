import argparse
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
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print(f"Serving {args.root_dir!r} at {url}")
    if args.open:
        webbrowser.open(url)

    run(args.root_dir, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
