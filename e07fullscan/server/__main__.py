import sys
from e07fullscan.server.app import run

if len(sys.argv) < 2:
    print("Usage: python -m e07fullscan.server <ROOT_DIR> [HOST] [PORT]")
    sys.exit(1)

host = sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0"
port = int(sys.argv[3]) if len(sys.argv) > 3 else 8000

run(sys.argv[1], host=host, port=port)
