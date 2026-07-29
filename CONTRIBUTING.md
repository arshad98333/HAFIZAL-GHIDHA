# Contributing

Thanks for considering a contribution to the GCC cold-chain fine-tuning
pipeline. This project is MIT-licensed (see [`LICENSE`](LICENSE)) — by
submitting a pull request, you agree your contribution is provided under
the same license.

## Before you write code

Open an issue first for anything beyond a small fix (typo, doc clarification,
an obvious bug with an obvious fix). For anything that touches
`rules_engine.py`, `guardrails.py`, or the label vocabulary, an issue is
required, not optional — see "Changing ground truth" below for why.

Check [`ROADMAP.md`](ROADMAP.md) before proposing new work — it may already
be planned, explicitly deferred, or explicitly out of scope ("Won't do"),
which saves you a PR that gets closed for reasons that had nothing to do
with code quality.

## Development setup

```bash
git clone <this-repo>
cd <this-repo>
python -m venv .venv
source .venv/bin/activate      # .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
cp .env.example .env           # fill in your own Atlas + Azure OpenAI values
pytest
```

You do not need live MongoDB or Azure credentials to run the test suite —
`pytest` covers the deterministic core (`rules_engine`, `guardrails`,
`knowledge_base`, `curriculum` allocation math, `logbook` coverage
structures, `simulate` synthesis) without a network round trip. Async
clients and the Mongo-backed logbook are exercised via
`python scripts/smoke_test.py` instead, which does need real credentials.

## Code standards

- **Type hints throughout**, `from __future__ import annotations` at the top
  of every module — match the existing style in `cold_chain/`.
- **Every external dependency is an env var**, validated by
  `cold_chain/config.py`'s `Settings` (pydantic-settings). Don't read
  `os.environ` directly elsewhere in the codebase.
- **Docstrings carry design rationale, not just parameter lists.** Look at
  `cold_chain/agentic_eval.py` or `cold_chain/config.py` for the style —
  when a threshold or a design choice isn't self-evident, the comment next
  to it explains why, often with the failure mode it's guarding against
  (e.g. the `AZURE_MAX_CONCURRENCY` comment in `config.py`). New non-obvious
  constants should follow the same pattern.
- **No bare `print()` in pipeline code** — use `cold_chain/telemetry.py`'s
  structured logging so output stays correlated by run id.
- Run `pytest` before opening a PR. CI (`.github/workflows/ci.yml`) runs the
  same suite across Python 3.11 and 3.12 plus a Docker build check; a PR
  that fails either blocks merge.

## Changing ground truth (`rules_engine.py`, `guardrails/`)

This is the one area with an explicit process, because of a standing
constraint the whole system depends on: **no label is ever produced by a
language model** (see "Standing constraints" in `README.md`). `rules_engine.py`
is the sole source of truth, and `guardrails/` is derived from the same
knowledge base plus a real failure sample.

If your change alters a threshold, adds a disposition rule, or edits a
guardrail:

1. Cite the source. Every rule traces to a cited instrument in
   `gcc_food_law_json/` — see `CHANGELOG_AND_VERIFICATION.md` in that
   directory for the verification format to follow.
2. Bump `RULES_VERSION` (see `README.md` § "Pre-wave-1 gates") so records
   generated before and after your change are distinguishable in the
   provenance envelope.
3. Add or update a test in `tests/test_rules_engine.py` or
   `tests/test_guardrails.py` that fails without your change and passes
   with it.
4. Explain in the PR description what real-world case motivated the
   change — "tightened a threshold" without a concrete failure it fixes
   will get a request for more context, not a merge.

## Adding a new jurisdiction

`gcc_food_law_json/` and `guardrails/` follow one schema per country
(`00_schema.json`). If you're adding coverage for a new jurisdiction (see
`ROADMAP.md`'s "Later / exploratory" section):

1. Validate your new profile against `00_schema.json` before opening a PR.
2. Every claim needs a citable primary source — competent authority,
   statute, or standard — not a paraphrase of another country's profile.
3. Add the corresponding guardrail file following the existing
   `0N_<country>_cold_chain_guardrails.json` naming and rule-count pattern.
4. Run `python scripts/audit_corpus_guardrails.py` against a small test
   wave before proposing the addition as complete.

## Security

- **Never commit `.env` or any file containing a real credential.** The
  `.gitignore` already excludes `.env` and its variants; don't work around
  that with `git add -f`.
- If you accidentally exposed a real credential in a commit, comment, or
  PR description, treat it as burned — rotate it (Atlas → Database Access →
  edit user; Azure AD → app registration → credentials) — don't rely on
  history rewriting alone; assume it was seen.
- Found a security issue that shouldn't be filed as a public GitHub issue
  (e.g. a way to bypass Gate A/B, or something that could leak the golden
  set)? Open a private security advisory via the repo's Security tab rather
  than a public issue.

## Pull request checklist

- [ ] `pytest` passes locally
- [ ] New/changed behavior has a test
- [ ] No `.env`, credentials, or generated run artifacts (`exports/*.jsonl`
      other than `wave_9001.jsonl`, `CORPUS_GUARDRAIL_AUDIT*`, `results.txt`)
      included in the diff — check `git status` against `.gitignore`
- [ ] If you touched `rules_engine.py` or `guardrails/`: `RULES_VERSION`
      bumped, source cited, test added (see above)
- [ ] PR description explains the *why*, not just the *what* — this
      project's existing docstrings are the bar to match

## Code of conduct

Be direct about disagreements, generous about intent. Critique the code and
the reasoning, not the person. Maintainers reserve the right to close
issues or PRs that don't meet this bar, with an explanation.
