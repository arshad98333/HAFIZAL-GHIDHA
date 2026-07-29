from __future__ import annotations

from cold_chain import knowledge_base as kb
from cold_chain import logbook as lb


def test_languages_is_english_only():
    assert lb.LANGUAGES == ["en"]


def test_jurisdictions_match_knowledge_base():
    assert lb.JURISDICTIONS == list(kb.JURISDICTIONS)
    assert len(lb.JURISDICTIONS) == 6


def test_all_cells_is_20_product_fault_pairs():
    cells = lb.all_cells()
    assert len(cells) == len(lb.PRODUCTS) * len(lb.FAULT_MODES) == 20
    assert len(set(cells)) == 20


def test_cell_key_roundtrip():
    key = lb.cell_key("finfish_seafood", "door_open")
    assert key == "finfish_seafood|door_open"
    product, fault = key.split("|")
    assert product == "finfish_seafood"
    assert fault == "door_open"


def test_empty_coverage_has_all_axes():
    cov = lb._empty_coverage()
    assert set(cov["cells"]) == set(lb.all_cells())
    assert set(cov["languages"]) == set(lb.LANGUAGES)
    assert set(cov["artifacts"]) == set(lb.ARTIFACTS)
    assert set(cov["jurisdictions"]) == set(lb.JURISDICTIONS)
    assert cov["total_kept"] == 0
