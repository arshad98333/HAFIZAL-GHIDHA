"""Domain-level errors. Library exceptions are translated to these at adapter boundaries."""

from __future__ import annotations


class ColdChainError(Exception):
    """Base error for the pipeline."""


class ValidationError(ColdChainError):
    """Invalid input at the system edge."""


class GateHaltError(ColdChainError):
    """A gate failed; pipeline must stop."""


class AdapterError(ColdChainError):
    """External dependency failed after retries."""


class ConfigurationError(ColdChainError):
    """Settings or environment invalid at startup."""
