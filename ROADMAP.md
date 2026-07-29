# Roadmap

This tracks where the pipeline is headed, not a promise of dates. Anything
here can move, split, or drop depending on what a real wave run surfaces.
If you want to pick one of these up, open an issue first — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Open-source initiative

This project is open source so the rule engine, the guardrail pack, and the
GCC food-law knowledge base stay reviewable by anyone who wants to check
them against the actual regulations — not just the maintainer. The goal
over time is a small community of contributors around three things: keeping
`gcc_food_law_json/` current as regulations change, extending the guardrail
pack, and hardening the pipeline itself (the "Near term" and "Later /
exploratory" items below).

**Community feature contest — $1,000 in Azure AI compute.** To kick this
off, the best community-submitted feature integration wins $1,000 worth of
Azure AI credits, sponsored by the maintainer. "Best" means: solves a real
gap on this roadmap (or a well-argued gap not yet listed), ships with
tests, and doesn't compromise the standing constraints in `README.md` (no
LLM-produced labels, no golden-set access from an agent environment, etc.).
How to enter:

1. Open an issue describing what you want to build and why, tagged
   `contest`, before starting work — this avoids two people building the
   same thing and lets the maintainer flag anything that conflicts with a
   standing constraint early.
2. Submit a PR referencing that issue, following [`CONTRIBUTING.md`](CONTRIBUTING.md).
3. Winner is chosen by the maintainer once the submission window closes;
   selection criteria and the closing date are posted on the pinned contest
   issue in the Issues tab (open one if it doesn't exist yet).

This is a starting point, not a permanent program — terms may be adjusted
run to run based on what submissions actually look like.

## Now

Recently shipped, still hardening:

- [x] Production Docker image + `.dockerignore`
- [x] GitHub Actions CI (pytest across Python 3.11/3.12, Docker build check)
- [x] Azure Container Apps Job deployment (`infra/main.json`, one-click
      "Deploy to Azure" button) with an OIDC-authenticated CD workflow
- [ ] Confirm the Container Apps Job's `replicaTimeoutSeconds` default
      (3600s) actually covers a full 663-record `generate` stage under real
      Azure OpenAI throughput, not just the smoke-sized `--max-records 10`
      runs it's been tested with so far

## Near term

- **Key Vault–backed secrets.** `infra/main.json` currently takes
  `mongodbUri` as a plain ARM `securestring` parameter set as a Container
  Apps secret. Move to referencing an Azure Key Vault secret URI instead, so
  rotating the Mongo credential doesn't require a redeploy.
- **Cron-triggered waves.** Container Apps Jobs support a `Schedule` trigger
  type in addition to `Manual`. Add an optional scheduled-trigger variant of
  the job (or a second job resource) for teams that want wave `generate`
  runs on a cadence instead of triggering by hand.
- **Lint/type-check in CI.** `ci.yml` runs `pytest` only. Add `ruff` and
  `mypy` as a fast-fail job before the test matrix — the codebase is
  type-hinted throughout (`from __future__ import annotations`,
  `pydantic-settings`) but nothing currently enforces it in CI.
- **Coverage reporting.** Wire `pytest --cov` into CI and publish the
  summary as a PR check, so a change that quietly drops test coverage on
  `rules_engine.py` or `guardrails.py` (the two files everything else
  depends on for ground truth) doesn't slip through review.
- **Bicep source for `infra/main.json`.** The ARM JSON is hand-authored and
  is the source of truth today. Move to a `.bicep` file compiled to JSON in
  CI (`az bicep build`), so infra changes get the same readability and
  modularity as the rest of the repo, with the JSON as a generated,
  reviewable artifact rather than something edited by hand.

## Later / exploratory

- **A second GCC-adjacent jurisdiction pack.** `gcc_food_law_json/` and
  `guardrails/` currently cover six GCC states. A structurally similar pack
  for a neighboring regulatory regime (e.g. Jordan, Egypt) would be the
  first real test of whether `knowledge_base.py` and `guardrails.py`'s
  loaders generalize past the GCC schema or need a v2.
- **Multi-provider model support.** `cold_chain/clients.py` has one external
  model provider (a single Azure OpenAI deployment used for render, screen,
  extract, and judge). Evaluate whether Gate B's self-consistency voting
  gets meaningfully more honest with a second, differently-trained judge
  model in the mix — the current design's own docstring in
  `agentic_eval.py` names this as the honest limitation versus a sealed
  human eval.
- **A read-only wave dashboard.** `scripts/generate_system_report.py`
  already produces `SYSTEM_EVALUATION_REPORT_wave*.md`. A small static-site
  or Streamlit view over the same Gate A/B history in MongoDB would make
  wave-over-wave drift (guardrail violation rate, cell F1, confusion pairs)
  visible without re-running the script each time.
- **Kubernetes/Helm alternative for the Job.** Azure Container Apps Jobs
  cover the common case; a Helm chart wrapping the same image for teams
  already standardized on AKS is a plausible ask once more than one team
  runs this outside Azure Container Apps specifically.

## Won't do (for now)

Recorded so it doesn't get re-proposed without context:

- **LLM-produced labels.** `rules_engine.py` is a pure function and stays
  that way — see "Standing constraints" in `README.md`. This is a design
  invariant, not a missing feature.
- **Golden-set access from any agent environment.** Same category — the
  separation is enforced by database-user scope (see `README.md` step 2),
  not application code, and that's intentional.

## How to propose something for this list

Open an issue describing the gap and, if you have one, the smallest change
that would close it. PRs that add a roadmap item without discussion first
are welcome too — just flag it as a proposal in the description so it's
clear it's not assumed-agreed-upon yet.
