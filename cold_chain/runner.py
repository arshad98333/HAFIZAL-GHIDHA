"""Backward-compatible re-export. Prefer cold_chain.cli.runner."""

from cold_chain.cli.runner import *  # noqa: F403
from cold_chain.cli.runner import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
