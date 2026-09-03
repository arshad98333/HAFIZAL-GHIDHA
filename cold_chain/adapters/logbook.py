"""Append-only logbook, backed by MongoDB Atlas instead of local JSONL.
Everything the curriculum agent reads for wave N was written by wave N-1
through this module, and only through this module — it is the compliance
fence between agents and the ledger of record.

Collections (database configurable, default ``cold_chain``; see
``mongo/indexes.py`` for the index/setup script):
    ledger              one document per completed wave, ``_id`` = wave
    coverage_state      singleton document, ``_id`` = 1, running fill counts
    generation_log      one document per attempted record (provenance envelope)
    wave_artifacts      arbitrary JSON blobs keyed by (wave, name) — plan.json, gate_a.json, ...
    decisions           append-only human-readable narrative chunks per wave
    autoresearch_log    every AutoResearch experiment, kept or reverted
    access_audit        every touch of a sensitive resource, human or agent

The golden set lives in a separate MongoDB Atlas database, reachable only from
a human workstation's connection string. This process's connection string
authenticates as a database user with a role scoped to ``mongodb_db_name``
only — see ``audit_access`` for the runtime trail that proves that held.
"""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import asdict, dataclass, field
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from cold_chain.config import Settings
from cold_chain.domain import catalog as cat
from cold_chain.observability.telemetry import get_logger

log = get_logger(__name__)

PRODUCTS = cat.PRODUCTS
FAULT_MODES = cat.FAULT_MODES
LANGUAGES = cat.LANGUAGES
ARTIFACTS = cat.ARTIFACTS
JURISDICTIONS = cat.JURISDICTIONS
cell_key = cat.cell_key
all_cells = cat.all_cells

_GENERATION_FLUSH_SIZE = 500
_COVERAGE_DOC_ID = 1


def _empty_coverage() -> dict[str, Any]:
    return {
        "cells": {c: {"kept": 0, "requested": 0, "last_wave": 0} for c in all_cells()},
        "languages": {lang: 0 for lang in LANGUAGES},
        "artifacts": {a: 0 for a in ARTIFACTS},
        "jurisdictions": {j: 0 for j in JURISDICTIONS},
        "adversarial": 0,
        "abstention": 0,
        "total_kept": 0,
    }


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


# --------------------------------------------------------------------------- #
# provenance envelope — attached to every generated record
# --------------------------------------------------------------------------- #


@dataclass
class Envelope:
    state_id: str
    wave: int
    cell: str
    language: str
    artifact_type: str
    jurisdiction: str
    is_adversarial: bool
    is_abstention: bool
    rng_seed: int
    rule_engine_sha: str
    prompt_template_hash: str
    generator_model: str
    renderer_model: str
    screener_verdict: str = "pending"
    round_trip_ok: bool | None = None
    human_reviewed: bool = False
    parent_request_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WaveRecord:
    wave: int
    requested: int
    kept: int
    gate_a_passed: bool
    gate_b_passed: bool
    worst_cell_f1: float
    worst_cell: str
    cells_passing: int
    mean_f1: float
    cell_f1: dict[str, float] = field(default_factory=dict)
    survival: dict[str, float] = field(default_factory=dict)
    top_confusions: list[list[str]] = field(default_factory=list)
    notes: str = ""


class Logbook:
    """Async facade over MongoDB Atlas. One instance per runner process.

    Not thread-safe across event loops; create one per ``asyncio.run``.
    """

    def __init__(self, settings: Settings, run_id: str):
        self._settings = settings
        self._run_id = run_id
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None
        self._gen_buffer: list[dict[str, Any]] = []
        self._gen_lock = asyncio.Lock()

    async def __aenter__(self) -> Logbook:
        self._client = AsyncIOMotorClient(self._settings.mongodb_uri)
        self._db = self._client[self._settings.mongodb_db_name]
        await self._client.admin.command("ping")
        await self._ensure_indexes()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.flush_generation()
        if self._client is not None:
            self._client.close()

    @property
    def db(self) -> AsyncIOMotorDatabase:
        assert self._db is not None, "Logbook used outside its async context"
        return self._db

    async def _ensure_indexes(self) -> None:
        db = self._db
        assert db is not None
        await db.generation_log.create_index([("wave", 1)])
        await db.generation_log.create_index([("wave", 1), ("cell", 1)])
        await db.generation_log.create_index([("wave", 1), ("outcome", 1)])
        await db.wave_artifacts.create_index([("wave", 1), ("name", 1)], unique=True)
        await db.decisions.create_index([("wave", 1), ("ts", 1)])
        await db.access_audit.create_index([("allowed", 1)])
        await db.gate_b_deliberation.create_index([("wave", 1)])
        await db.live_logs.create_index([("ts", 1)], expireAfterSeconds=30 * 24 * 3600)
        await db.qa_log.create_index([("ts", -1)])
        await db.qa_log.create_index([("jurisdiction", 1)])
        await db.qa_log.create_index([("kind", 1)])

    # ----------------------------------------------------------------- #
    # Gate B deliberation trail — the audit surface that replaces a human
    # reviewer being in the room. Every judge vote, every escalation.
    # ----------------------------------------------------------------- #

    async def write_deliberation(self, wave: int, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        assert self._db is not None
        for r in records:
            r["wave"] = wave
            r["run_id"] = self._run_id
            r["ts"] = _now()
        await self._db.gate_b_deliberation.insert_many(records, ordered=False)

    # ----------------------------------------------------------------- #
    # generation log (buffered — 1,000 single-document inserts per wave
    # would round-trip far more than necessary)
    # ----------------------------------------------------------------- #

    async def write_generation(
        self, envelope: Envelope, outcome: str, note: str = "", extra: dict[str, Any] | None = None
    ) -> None:
        row = envelope.as_dict()
        row["outcome"] = outcome
        row["note"] = note
        row["run_id"] = self._run_id
        row["ts"] = _now()
        if extra:
            row.update(extra)
        async with self._gen_lock:
            self._gen_buffer.append(row)
            if len(self._gen_buffer) >= _GENERATION_FLUSH_SIZE:
                await self._flush_generation_locked()

    async def flush_generation(self) -> None:
        async with self._gen_lock:
            await self._flush_generation_locked()

    async def _flush_generation_locked(self) -> None:
        if not self._gen_buffer:
            return
        batch, self._gen_buffer = self._gen_buffer, []
        assert self._db is not None
        await self._db.generation_log.insert_many(batch, ordered=False)
        log.info("flushed generation batch", extra={"extra_fields": {"n": len(batch)}})

    async def read_generation(self, wave: int) -> list[dict[str, Any]]:
        assert self._db is not None
        return await self._db.generation_log.find({"wave": wave}).to_list(length=None)

    async def survival_rates(self, wave: int) -> dict[str, float]:
        rows = await self.read_generation(wave)
        req: dict[str, int] = {}
        kept: dict[str, int] = {}
        for r in rows:
            req[r["cell"]] = req.get(r["cell"], 0) + 1
            if r["outcome"] == "kept":
                kept[r["cell"]] = kept.get(r["cell"], 0) + 1
        return {c: round(kept.get(c, 0) / n, 3) for c, n in req.items() if n}

    # ----------------------------------------------------------------- #
    # coverage — singleton document
    # ----------------------------------------------------------------- #

    async def load_coverage(self) -> dict[str, Any]:
        assert self._db is not None
        doc = await self._db.coverage_state.find_one({"_id": _COVERAGE_DOC_ID})
        if not doc:
            return _empty_coverage()
        doc.pop("_id", None)
        return doc["state"]

    async def update_coverage(self, wave: int) -> dict[str, Any]:
        """Recompute coverage from this wave's generation rows. Idempotent per
        wave as long as it is called at most once per wave (the runner
        enforces this)."""
        cov = await self.load_coverage()
        for r in await self.read_generation(wave):
            cell = r["cell"]
            cov["cells"].setdefault(cell, {"kept": 0, "requested": 0, "last_wave": 0})
            cov["cells"][cell]["requested"] += 1
            cov["cells"][cell]["last_wave"] = wave
            if r["outcome"] == "kept":
                cov["cells"][cell]["kept"] += 1
                cov["languages"][r["language"]] = cov["languages"].get(r["language"], 0) + 1
                cov["artifacts"][r["artifact_type"]] = cov["artifacts"].get(r["artifact_type"], 0) + 1
                cov.setdefault("jurisdictions", {})
                cov["jurisdictions"][r["jurisdiction"]] = cov["jurisdictions"].get(r["jurisdiction"], 0) + 1
                cov["adversarial"] += int(r["is_adversarial"])
                cov["abstention"] += int(r["is_abstention"])
                cov["total_kept"] += 1
        assert self._db is not None
        await self._db.coverage_state.replace_one(
            {"_id": _COVERAGE_DOC_ID},
            {"_id": _COVERAGE_DOC_ID, "state": cov, "updated_at": _now()},
            upsert=True,
        )
        return cov

    # ----------------------------------------------------------------- #
    # ledger
    # ----------------------------------------------------------------- #

    async def append_ledger(self, rec: WaveRecord) -> None:
        assert self._db is not None
        row = asdict(rec)
        row["run_id"] = self._run_id
        row["ts"] = _now()
        await self._db.ledger.replace_one({"_id": rec.wave}, {"_id": rec.wave, **row}, upsert=True)

    async def read_ledger(self) -> list[dict[str, Any]]:
        assert self._db is not None
        return await self._db.ledger.find({}).sort("_id", 1).to_list(length=None)

    async def last_wave(self) -> int:
        led = await self.read_ledger()
        return led[-1]["wave"] if led else 0

    # ----------------------------------------------------------------- #
    # wave artifacts (plan.json, gate_a.json, gate_b.json, ...)
    # ----------------------------------------------------------------- #

    async def write_json(self, wave: int, name: str, payload: dict[str, Any]) -> None:
        assert self._db is not None
        await self._db.wave_artifacts.replace_one(
            {"wave": wave, "name": name},
            {"wave": wave, "name": name, "payload": payload, "run_id": self._run_id, "ts": _now()},
            upsert=True,
        )

    async def read_json(self, wave: int, name: str) -> dict[str, Any] | None:
        assert self._db is not None
        doc = await self._db.wave_artifacts.find_one({"wave": wave, "name": name})
        return doc["payload"] if doc else None

    # ----------------------------------------------------------------- #
    # decisions narrative
    # ----------------------------------------------------------------- #

    async def append_decisions(self, wave: int, text: str) -> None:
        assert self._db is not None
        await self._db.decisions.insert_one(
            {"wave": wave, "content": text.rstrip(), "run_id": self._run_id, "ts": _now()}
        )

    async def read_decisions(self, wave: int) -> str:
        assert self._db is not None
        docs = await self._db.decisions.find({"wave": wave}).sort("ts", 1).to_list(length=None)
        return "\n\n".join(d["content"] for d in docs)

    # ----------------------------------------------------------------- #
    # AutoResearch experiment log
    # ----------------------------------------------------------------- #

    async def append_autoresearch(
        self,
        wave: int,
        hypothesis: str,
        diff_summary: str,
        metric_before: float,
        metric_after: float,
        decision: str,
        duration_s: float,
    ) -> None:
        assert self._db is not None
        await self._db.autoresearch_log.insert_one(
            {
                "wave": wave,
                "hypothesis": hypothesis,
                "diff_summary": diff_summary,
                "metric_before": metric_before,
                "metric_after": metric_after,
                "decision": decision,
                "duration_s": duration_s,
                "run_id": self._run_id,
                "ts": _now(),
            }
        )

    # ----------------------------------------------------------------- #
    # access audit — standing constraint #2: the golden set is never mounted
    # into an agent environment. This is the trail that proves it held.
    # ----------------------------------------------------------------- #

    # ----------------------------------------------------------------- #
    # compliance Q&A chat (/compliance/ask) audit trail -- one document per
    # question, holding the retrieved context and every chained step's
    # output. This is the record a human reviews if K2 said something
    # wrong; it is not read by anything else in the pipeline.
    # ----------------------------------------------------------------- #

    async def write_qa_log(
        self,
        *,
        question: str,
        jurisdiction: str | None,
        product: str | None,
        context_block: str,
        steps: list[dict[str, Any]],
        status: str,
        error: str | None = None,
        citation_eval: dict[str, Any] | None = None,
        retry_count: int = 0,
        kind: str = "ask",
        scenario: dict[str, Any] | None = None,
    ) -> None:
        assert self._db is not None
        await self._db.qa_log.insert_one(
            {
                # kind distinguishes /compliance/ask ("ask") from LiveOps
                # narrations ("liveops") in the same collection -- one audit
                # trail, not two, since both are K2 chains grounded the same
                # way and reviewed the same way.
                "kind": kind,
                "question": question,
                "jurisdiction": jurisdiction,
                "product": product,
                "context_block": context_block,
                "steps": steps,
                "status": status,
                "error": error,
                # citation_eval: compliance_qa.evaluate_citations() output --
                # which rule IDs the model cited vs. which were actually
                # retrieved. retry_count: how many K2 rate-limit/backoff
                # cycles this exchange needed (K2's tier is low-RPM).
                "citation_eval": citation_eval,
                "retry_count": retry_count,
                # scenario: the full TruckScenario payload for a LiveOps
                # narration (None for /compliance/ask entries) -- lets a
                # human reviewer see exactly what the model was narrating.
                "scenario": scenario,
                "run_id": self._run_id,
                "ts": _now(),
            }
        )

    async def audit_access(self, principal: str, resource: str, action: str, allowed: bool) -> None:
        assert self._db is not None
        await self._db.access_audit.insert_one(
            {
                "principal": principal,
                "resource": resource,
                "action": action,
                "allowed": allowed,
                "run_id": self._run_id,
                "ts": _now(),
            }
        )
        if not allowed:
            log.error(
                "blocked access",
                extra={
                    "extra_fields": {
                        "principal": principal,
                        "resource": resource,
                        "action": action,
                    }
                },
            )
