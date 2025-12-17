from __future__ import annotations

import argparse
import sys
import time

from lightpanda_local.lightpanda_service import (
    DEFAULT_LIGHTPANDA_DOWNLOAD_URL,
    start_lightpanda_server,
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Download (if missing) and run Lightpanda CDP server."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=9222, type=int)
    parser.add_argument("--download-url", default=DEFAULT_LIGHTPANDA_DOWNLOAD_URL)
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Block and keep the server running (prints logs).",
    )
    args = parser.parse_args(argv)

    process = start_lightpanda_server(
        host=args.host,
        port=args.port,
        download_url=args.download_url,
        capture_logs=args.wait,
    )
    print(f"Lightpanda PID={process.pid} listening on {args.host}:{args.port}")

    if not args.wait:
        return 0

    try:
        while True:
            line = process.stdout.readline() if process.stdout else ""
            if line:
                print(line.rstrip("\n"))
            else:
                time.sleep(0.2)
    except KeyboardInterrupt:
        process.terminate()
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
