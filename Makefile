.PHONY: install dev test test-fast test-integration lint format typecheck check build clean \
	health run run-smoke run-wave run-rescore run-full api \
	local-setup smoke-run wave-run local-audit kpi preflight rescore

PYTHON ?= python3
VENV ?= .venv
WAVE ?= 1
PROFILE ?= rescore
MAX ?= 10

ifeq ($(wildcard $(VENV)/bin/python),)
  PY := $(PYTHON)
  PIP := $(PYTHON) -m pip
  RUFF := $(PYTHON) -m ruff
  MYPY := $(PYTHON) -m mypy
  PYTEST := $(PYTHON) -m pytest
else
  PY := $(VENV)/bin/python
  PIP := $(VENV)/bin/pip
  RUFF := $(VENV)/bin/ruff
  MYPY := $(VENV)/bin/mypy
  PYTEST := $(VENV)/bin/pytest
endif

# --------------------------------------------------------------------------- #
# THE single command — everything ties here
# --------------------------------------------------------------------------- #

run:
	$(PY) scripts/local_run.py run --wave $(WAVE) --profile $(PROFILE)

run-smoke:
	$(PY) scripts/local_run.py run --wave $(WAVE) --profile smoke

run-wave:
	$(PY) scripts/local_run.py run --wave $(WAVE) --profile wave

run-rescore:
	$(PY) scripts/local_run.py run --wave $(WAVE) --profile rescore

run-full:
	$(PY) scripts/local_run.py run --wave $(WAVE) --profile full

# --------------------------------------------------------------------------- #
# Setup & quality
# --------------------------------------------------------------------------- #

install:
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV) || true
	$(PIP) install --upgrade pip pip-tools
	$(PIP) install -r requirements-dev.txt

lock:
	$(PIP) install pip-tools
	$(PYTHON) -m piptools compile requirements.in -o requirements.txt --resolver=backtracking
	$(PYTHON) -m piptools compile requirements-dev.in -o requirements-dev.txt --resolver=backtracking

dev:
	@echo "Single command: make run WAVE=1 PROFILE=rescore"

test-fast:
	PYTHONPATH=. $(PYTEST) tests/unit tests/test_*.py -v --ignore=tests/integration -m "not integration"

test-integration:
	PYTHONPATH=. $(PYTEST) tests/integration -v -m integration

test: test-fast test-integration

lint:
	$(RUFF) check cold_chain tests scripts
	$(RUFF) format --check cold_chain tests scripts

format:
	$(RUFF) format cold_chain tests scripts
	$(RUFF) check --fix cold_chain tests scripts

typecheck:
	$(MYPY) cold_chain/config.py cold_chain/ports.py cold_chain/adapters/fakes.py --ignore-missing-imports --follow-imports=skip

check: lint typecheck test-fast

build:
	docker build -t cold-chain-pipeline:local .

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

health:
	$(PY) -m cold_chain.runner health

api:
	$(PY) scripts/api_server.py --host 0.0.0.0 --port 8080

api-dev:
	$(PY) scripts/api_server.py --host 0.0.0.0 --port 8080 --reload

# --------------------------------------------------------------------------- #
# Legacy aliases (delegate to run profiles)
# --------------------------------------------------------------------------- #

local-setup:
	$(PY) scripts/local_run.py step setup

smoke-run: run-smoke

wave-run: run-wave

rescore: run-rescore

local-audit:
	$(PY) scripts/local_run.py audit --wave $(WAVE)

kpi:
	$(PY) scripts/kpi_dashboard.py --wave $(WAVE)

preflight:
	$(PY) -m cold_chain.runner preflight --wave $(WAVE)
