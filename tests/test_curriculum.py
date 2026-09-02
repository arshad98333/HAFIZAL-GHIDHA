from __future__ import annotations

import asyncio

from cold_chain import curriculum
from cold_chain import logbook as lb


class FakeLogbook:
    """Minimal stand-in for lb.Logbook's read surface used by
    curriculum.build_plan / plan_wave. No MongoDB involved."""

    def __init__(self, coverage=None, ledger=None, survival=None):
        self._coverage = coverage or lb._empty_coverage()
        self._ledger = ledger or []
        self._survival = survival or {}
        self.written_json: dict[tuple[int, str], dict] = {}
        self.decisions: list[tuple[int, str]] = []

    async def load_coverage(self):
        return self._coverage

    async def read_ledger(self):
        return self._ledger

    async def survival_rates(self, wave):
        return self._survival

    async def write_json(self, wave, name, payload):
        self.written_json[(wave, name)] = payload

    async def append_decisions(self, wave, text):
        self.decisions.append((wave, text))


def run(coro):
    return asyncio.run(coro)


def test_wave_focus_has_eight_waves_and_holdout_last():
    assert set(curriculum.WAVE_FOCUS) == set(range(1, 9))
    assert curriculum.WAVE_FOCUS[8].get("holdout") is True
    for w in range(1, 8):
        assert not curriculum.WAVE_FOCUS[w].get("holdout")


def test_balanced_split_sums_to_total():
    for total in (0, 1, 4, 663, 265):
        for keys in (["a"], ["a", "b"], list(lb.JURISDICTIONS), lb.ARTIFACTS):
            split = curriculum._balanced_split(total, keys)
            assert sum(split.values()) == total
            assert set(split) == set(keys)


def test_build_plan_totals_match_wave_size(monkeypatch):
    from cold_chain.config import Settings

    settings = Settings(
        mongodb_uri="mongodb://localhost",
        azure_endpoint="https://x",
        foundry_project_endpoint="https://x",
        foundry_compute_cluster="c",
        foundry_base_model="m",
        training_region="r",
        wave_size=663,
        cell_target=265,
    )
    book = FakeLogbook()
    plan = run(curriculum.build_plan(1, book, settings))
    # Proportional-then-rounded allocation can land within a few records of
    # wave_size (see curriculum.build_plan's rounding/spare-distribution
    # comments) -- not required to hit it exactly.
    assert abs(plan["total"] - 663) <= 5
    assert plan["wave"] == 1
    assert plan["holdout"] is False
    # wave 1 only targets in_spec/door_open per WAVE_FOCUS
    fault_modes = {a["fault_mode"] for a in plan["allocations"]}
    assert fault_modes <= {"in_spec", "door_open"}
    # per-cell cap is 20% of wave_size
    max_per_cell = int(663 * 0.20)
    assert all(a["count"] <= max_per_cell for a in plan["allocations"])
    # jurisdiction/artifact/language splits sum to the cell count
    for a in plan["allocations"]:
        assert sum(a["jurisdiction_split"].values()) == a["count"]
        assert sum(a["artifact_split"].values()) == a["count"]
        assert sum(a["language_split"].values()) == a["count"]
        assert set(a["language_split"]) == {"en"}


def test_build_plan_holdout_wave_flagged():
    from cold_chain.config import Settings

    settings = Settings(
        mongodb_uri="mongodb://localhost",
        azure_endpoint="https://x",
        foundry_project_endpoint="https://x",
        foundry_compute_cluster="c",
        foundry_base_model="m",
        training_region="r",
        wave_size=663,
        cell_target=265,
    )
    book = FakeLogbook()
    plan = run(curriculum.build_plan(8, book, settings))
    assert plan["holdout"] is True


def test_plan_wave_writes_plan_json_without_azure_client():
    from cold_chain.config import Settings

    settings = Settings(
        mongodb_uri="mongodb://localhost",
        azure_endpoint="https://x",
        foundry_project_endpoint="https://x",
        foundry_compute_cluster="c",
        foundry_base_model="m",
        training_region="r",
        wave_size=663,
        cell_target=265,
    )
    book = FakeLogbook()
    plan = run(curriculum.plan_wave(1, book, azure=None, settings=settings))
    assert book.written_json[(1, "plan.json")] == plan
    assert book.decisions and book.decisions[0][0] == 1
