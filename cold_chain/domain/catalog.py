"""Domain catalog: products, fault modes, cells — no I/O."""

from __future__ import annotations

from cold_chain.domain.knowledge_base import JURISDICTIONS

PRODUCTS = ["finfish_seafood", "table_eggs", "chilled_dairy", "frozen_goods"]
FAULT_MODES = ["in_spec", "door_open", "compressor_fail", "setpoint_drift", "sensor_artifact"]
LANGUAGES = ["en"]
ARTIFACTS = ["logger_csv", "chat_message", "qc_form_ocr", "voice_note"]
JURISDICTIONS = list(JURISDICTIONS)


def cell_key(product: str, fault_mode: str) -> str:
    return f"{product}|{fault_mode}"


def all_cells() -> list[str]:
    return [cell_key(p, f) for p in PRODUCTS for f in FAULT_MODES]
