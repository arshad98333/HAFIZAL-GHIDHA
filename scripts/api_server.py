#!/usr/bin/env python3
"""Start the FastAPI HTTP server.

    python scripts/api_server.py
    python scripts/api_server.py --host 0.0.0.0 --port 8080 --reload

Environment: same .env as the CLI pipeline (MONGODB_URI, AZURE_OPENAI_ENDPOINT, ...).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="GCC Cold-Chain Pipeline API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev only)")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "cold_chain.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
