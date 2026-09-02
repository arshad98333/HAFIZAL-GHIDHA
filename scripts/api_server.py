#!/usr/bin/env python3
"""Start the FastAPI HTTP server.

    python scripts/api_server.py
    python scripts/api_server.py --host 0.0.0.0 --port 8080 --reload

Windows (recommended - always uses venv python):

    .\\scripts\\api_server.ps1

Environment: same .env as the CLI pipeline (MONGODB_URI, AZURE_OPENAI_ENDPOINT, ...).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows: "python" on PATH often is not the venv interpreter even after Activate.ps1.
# Re-exec with venv\\Scripts\\python.exe when it exists and we are not already on it.
_VENV_PY = ROOT / "venv" / "Scripts" / "python.exe"
if _VENV_PY.exists():
    try:
        if Path(sys.executable).resolve() != _VENV_PY.resolve():
            os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])
    except OSError:
        pass

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="GCC Cold-Chain Pipeline API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev only)")
    args = parser.parse_args()

    try:
        import uvicorn
    except ModuleNotFoundError:
        print("uvicorn is not installed for this Python interpreter:", file=sys.stderr)
        print(f"  {sys.executable}", file=sys.stderr)
        print(file=sys.stderr)
        print("Fix:", file=sys.stderr)
        print(f"  {sys.executable} -m pip install fastapi uvicorn", file=sys.stderr)
        print("  .\\scripts\\api_server.ps1", file=sys.stderr)
        return 1

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
