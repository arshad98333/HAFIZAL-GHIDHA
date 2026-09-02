# ADR 0001: Apply production engineering guidebook

## Context

The repository is a working batch ML pipeline with strong domain design (deterministic rules, guardrails, provenance) but gaps against the Production Grade Build Guidebook: no lockfile, no Makefile, flat package layout, no formal ports/fakes, CI not equal to local `make check`.

## Decision

Apply the guidebook in three gated phases with maker-checker: Make → Check → Gate before each next phase.

## Alternatives considered

- **Big-bang rewrite:** Rejected — violates guidebook "small and continuous" rule.
- **HTTP API first:** Rejected — this is a Job, not a web service; health is CLI-based.
- **Skip package split:** Rejected — domain/adapter separation is the highest-value structural change for testability.

## Consequences

- Phase 1: reproducibility (Makefile, lockfile, fakes, docs) without moving all modules.
- Phase 2: structural move to `domain/`, `adapters/`, `cli/`, `observability/` with re-exports.
- Phase 3: CI enforcement, health CLI, Key Vault, release docs.
- `training.sft` gap addressed via `TrainingSubmitter` protocol + honest stub.

## Status

Accepted — implementation in progress.
