syntax=docker/dockerfile:1

FROM python:3.11-slim AS base

# System deps: build tools for scientific-Python wheels (numpy/scikit-learn),
# ca-certificates for Azure AAD/TLS calls, then removed from the final layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so code-only changes don't bust the layer cache.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code and reference data. .dockerignore keeps out .env, .git,
# __pycache__, .venv, exports/ generated logs, etc.
COPY cold_chain/ ./cold_chain/
COPY gcc_food_law_json/ ./gcc_food_law_json/
COPY guardrails/ ./guardrails/
COPY scripts/ ./scripts/
COPY pytest.ini CURRICULUM.md AUTORESEARCH.md ./

# Never bake credentials into the image -- these are supplied at run time via
# `docker run --env-file .env ...` or the orchestrator's secret store.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 1000 pipeline
USER pipeline

# No default stage: a wave is a sequence of separate, resumable invocations
# (plan -> generate -> gate-a -> train -> gate-b), not one long-running
# process. Pass the stage and wave at `docker run` time, e.g.:
#   docker run --env-file .env <image> generate --wave 1
ENTRYPOINT ["python", "-m", "cold_chain.runner"]
CMD ["--help"]
