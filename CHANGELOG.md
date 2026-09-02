# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Production guidebook foundation: `docs/scope.md`, `docs/architecture.md`, Makefile, lockfile, ports/fakes, maker-checker phase gates.
- `docker-compose.yml` for local MongoDB integration tests.
- CLI `health` and `ready` commands for Container Apps Job probes.
- Package layout: `cold_chain/domain`, `adapters`, `cli`, `observability` with backward-compatible shims.
- `FoundryTrainingSubmitter` adapter; domain error types; `docs/operations.md`.
- CI runs `make check`, coverage floor (70%), pip-audit, Docker health; weekly schedule.
- Optional Key Vault secret URI for MongoDB in `infra/main.json`.

### Changed

- CI runs `make check` instead of pytest-only.
- README documents `make install`, `make test-fast`, and `health` CLI.
- CONTRIBUTING adds Definition of Done checklist.
