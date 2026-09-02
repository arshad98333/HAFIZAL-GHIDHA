"""Production adapters for external systems."""

from cold_chain.adapters.agentic_eval import AutoGateB
from cold_chain.adapters.clients import AzureClient, ContentSafetyClient, StudentClient
from cold_chain.adapters.fakes import FakeContentSafety, FakeLLM, FakeLogbook, FakeTrainingSubmitter
from cold_chain.adapters.logbook import Logbook, WaveRecord
from cold_chain.adapters.training import FoundryTrainingSubmitter

__all__ = [
    "AutoGateB",
    "AzureClient",
    "ContentSafetyClient",
    "FakeContentSafety",
    "FakeLLM",
    "FakeLogbook",
    "FakeTrainingSubmitter",
    "FoundryTrainingSubmitter",
    "Logbook",
    "StudentClient",
    "WaveRecord",
]
