.PHONY: install dev test test-fast test-integration lint format typecheck check build clean health

PYTHON ?= python3
ifeq ($(wildcard $(VENV)/bin/python),)
  PY := $(PYTHON)
  PIP := $(PYTHON) -m pip
  RUFF := $(PYTHON) -m ruff
  MYPY := $(PYTHON) -m mypy
else
  PY := $(VENV)/bin/python
  PIP := $(VENV)/bin/pip
  RUFF := $(VENV)/bin/ruff
  MYPY := $(VENV)/bin/mypy
endif
VENV ?= .venv

install:
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV) || true
	$(PIP) install --upgrade pip pip-tools
	$(PIP) install -r requirements-dev.txt

dev:
	@echo "Run a stage, e.g.: $(PY) -m cold_chain.runner plan --wave 1"

test-fast:
	PYTHONPATH=. $(PY) -m pytest tests/unit tests/test_*.py -v --ignore=tests/integration -m "not integration"

test-integration:
	PYTHONPATH=. $(PY) -m pytest tests/integration -v -m integration

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
