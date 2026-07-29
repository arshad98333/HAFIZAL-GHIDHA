# Manual testing guide

Step-by-step commands to stand up the pipeline, generate a wave, and check
the result -- both a small smoke-scale run and a full ~5,304-record corpus
quality/guardrail audit. Run all of this from the repo root, with your
virtualenv active. Every command below is copy-pasteable in order.

Read `README.md` first if you haven't set up `.env` yet ("Fill in `.env`").

---

## 0. One-time setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt     # includes pytest + openai on top of requirements.txt
cp .env.example .env
# edit .env: MONGODB_URI, AZURE_OPENAI_ENDPOINT, FOUNDRY_* (see README "Fill in .env")
az login                         # AAD auth for Azure OpenAI, if not already signed in
```

## 1. Run the automated test suite

Confirms the deterministic core (rule engine, guardrails, knowledge base,
curriculum math) is correct before you spend any API calls on it.

```bash
pytest
```

Expect: all tests pass, no network/credentials required for this step.

## 2. Confirm every external dependency is reachable

```bash
python scripts/smoke_test.py
```

Expect: `MongoDB Atlas`, `Azure OpenAI chat`, `Azure OpenAI embeddings`,
`Knowledge base`, `Guardrail pack` all `PASS`. `Managed training compute` and
`Student inference endpoint` are expected to be skipped/fail until you've
deployed a checkpoint -- that's normal at this stage.

## 3. If you've run this pipeline before under an older schema

Skip this step on a first-ever run. Otherwise:

```bash
python scripts/reset_pipeline_state.py --dry-run     # see what's currently in Mongo
python scripts/reset_pipeline_state.py --yes         # clear it (access_audit is kept)
```

Why: `plan.json` / `coverage_state` / `generation_log` are schema-coupled to
whatever version of the pipeline wrote them. Mixing an old wave's state with
the current code produces exactly the kind of error you'd expect from that
(a `KeyError` on a retired covariate value, or `plan` refusing because
coverage looks "already full"). See README "If you're re-running a wave
after upgrading the pipeline."

## 4. Run one small, cheap test wave end to end

Cap the record count so you're not spending 663 records' worth of API calls
just to check the wiring works:

```bash
python -m cold_chain.runner plan     --wave 1
python -m cold_chain.runner generate --wave 1 --max-records 10
python -m cold_chain.runner gate-a   --wave 1
```

Expect: `plan` prints a JSON allocation; `generate` logs progress and ends
with `generation complete`; `gate-a` prints every metric against its bound
and either `Gate A passed` or exits `2` with a failure list. A failure here
on a 10-record test wave is common and expected (Gate A's near-duplicate
and cell-fill-deviation checks are tuned for a full 663-record wave, not 10)
-- the point of this step is confirming the commands run cleanly end to end,
not passing Gate A yet.

## 5. Look at what was actually generated

```bash
python scripts/export_wave.py --wave 1              # kept only
python scripts/export_wave.py --wave 1 --all         # everything, with drop reasons
```

Open `exports/generation_log_wave01.jsonl` and read a few lines. Check:
`rendered_text` never states a disposition outright, `disposition` matches
what you'd expect from the temperature series, `jurisdiction` is one of the
six GCC codes, `screener_verdict` is `CONSISTENT` for kept records.

## 6. Audit guardrail compliance across the corpus

This is the "check quality of the data against guardrails" step. No LLM
calls -- it runs the guardrail pack's regex checks over every kept record
and reports violation rates broken down by cell, jurisdiction, and artifact
type, plus a corpus-wide check that `expedite_sale` was never autonomously
emitted (GCC-EDGE-015).

```bash
# just wave 1
python scripts/audit_corpus_guardrails.py --wave 1

# once you've generated more waves, the full corpus
python scripts/audit_corpus_guardrails.py --all-waves \
    --out CORPUS_GUARDRAIL_AUDIT.md --csv CORPUS_GUARDRAIL_AUDIT.csv
```

Read `CORPUS_GUARDRAIL_AUDIT.md`. What "good" looks like:

- Overall violation rate at or below 1% (the same bound Gate A itself
  enforces via `gates.GATE_A["guardrail_violation_rate"]`)
- The GCC-EDGE-015 (`expedite_sale`) section says **Held: 0 kept records**
- No single cell/jurisdiction/artifact-type combination sitting far above
  the overall rate (that would mean a specific renderer prompt or fault mode
  is systematically leaking, not a handful of random misses)

## 7. Simulate real-time processing

Feeds the same kept records through the guardrail layer one at a time, the
way a deployed agent gating a live queue of incoming artifacts would --
useful for eyeballing throughput/latency and watching flags happen live
instead of reading a static end-of-run report.

```bash
python scripts/live_stream_demo.py --wave 1
python scripts/live_stream_demo.py --all-waves --shuffle --delay 0.02
```

Expect a live-updating status line (`records/sec`, running violation count,
disposition mix), a full line printed for each flagged record as it's hit,
and a summary block at the end with throughput and p99 per-record latency
(this layer alone should be sub-millisecond per record -- it's pure regex,
no network).

## 8. Second-pass review (optional, costs real API calls)

```bash
python scripts/azure_review.py --ping
python scripts/azure_review.py --wave 1 --limit 20 --out azure_review_wave01.jsonl
```

Read the module docstring in `scripts/azure_review.py` first -- this calls
the *same* Azure deployment the pipeline uses internally, so agreement here
is a same-model consistency check, not independent corroboration.

## 9. Full tied-together report

```bash
python scripts/generate_system_report.py --wave 1 --review-limit 20
```

Writes `SYSTEM_EVALUATION_REPORT_wave01.md`: Gate A/B results, coverage,
drop-reason breakdown, and the review from step 8, in one file.

## 10. Scaling up to the full ~5,304-record corpus

Once step 4 looks right at small scale, run every wave at full size (drop
`--max-records`):

```bash
for w in 1 2 3 4 5 6 7 8; do
    python -m cold_chain.runner plan     --wave $w
    python -m cold_chain.runner generate --wave $w
    python -m cold_chain.runner gate-a   --wave $w
    # gate-b / train once you have a deployed checkpoint or a sealed-eval results file
done
```

(PowerShell equivalent: `foreach ($w in 1..8) { python -m cold_chain.runner plan --wave $w; ... }`.)

Then repeat steps 6 and 7 with `--all-waves` for the full-corpus picture, and
step 9 per wave for the tied-together report. Wave 8 is the holdout wave
(rendered by a different model, never trained on -- CURRICULUM.md section 3);
its `gate-b` output is expected to look different from waves 1-7, that's by
design, not a regression.
