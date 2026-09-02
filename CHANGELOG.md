# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Production guidebook foundation: `docs/scope.md`, `docs/architecture.md`, Makefile, lockfile, ports/fakes, maker-checker phase gates.
- `docker-compose.yml` for local MongoDB integration tests.
- CLI `health` and `ready` commands for Container Apps Job probes.

### Changed

- Package layout: `cold_chain/domain`, `adapters`, `cli`, `observability` with backward-compatible re-exports.
- CI runs `make check` (format, lint, typecheck, tests, coverage floor).
