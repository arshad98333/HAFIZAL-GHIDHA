"""FastAPI HTTP surface for the cold-chain pipeline."""

from cold_chain.api.app import create_app

__all__ = ["create_app"]
