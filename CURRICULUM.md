# CURRICULUM.md

Instruction file for the curriculum agent. Read in full at the start of every wave,
together with `logs/ledger.jsonl` and `logs/coverage.json`.

You do not write code. You do not assign labels. You emit a generation plan:
663 requests allocated across the coverage matrix, with a written rationale.

---

## 1. What we are building

A student model that reads messy GCC cold-chain artifacts and emits strict JSON:
extracted event fields, plus a disposition drawn from the rule engine's label space.
The student never computes. It perceives fields; Python computes everything else.

Total corpus: **5,304 records across 8 waves of 663.** English-language artifacts
only (see section 2) -- this is a scoped, portfolio-scale corpus, not the earlier
10,000-record / bilingual design.

---

## 2. Coverage matrix

### Primary strata — these get statistical power

20 cells: `product × fault_mode`, nominal target 265 records each (20 × 265 = 5,300;
the remaining 4 records land wherever the deficit scorer sends them — see section 4).

Products:
- `finfish_seafood` — hamour, kingfish, shrimp; chilled 0-4C (GSO band `chilled_fresh_seafood`)
- `table_eggs` — chilled 0-5C (GSO band `chilled_general`)
- `chilled_dairy` — chilled 0-5C (GSO band `chilled_general`)
- `frozen_goods` — <=-18C, refreeze flag -12C (GSO band `frozen`)

Product temperature bands are sourced from `guardrails/00_gcc_base_guardrails.json`
(`temperature_bands`, in turn GSO 150-1 / GSO 150-2), not hardcoded in the rule
engine — see `rules_engine.py` and `guardrails.py`.

Fault modes:
- `in_spec` — control group, no excursion
- `door_open` — cross-dock exposure, ambient-driven
- `compressor_fail` — sustained loss of refrigeration
- `setpoint_drift` — slow, easy to miss
- `sensor_artifact` — stuck-at, spike, disconnect; looks like a fault but is not

### Balanced covariates — reported, never gated on

Within each ~265-cell, assign by balanced split so no covariate correlates with the label.

- `language`: `en` only. Earlier revisions of this pipeline also balanced across
  `ar_msa` / `ar_arabizi` / `code_switched`; that axis is out of scope for this
  corpus. All rendering, screening, and extraction prompts are English-only.
- `artifact_type`: `logger_csv`, `chat_message`, `qc_form_ocr`, `voice_note` — split evenly.
- `jurisdiction`: one of the six GCC states (`AE`, `SA`, `QA`, `KW`, `OM`, `BH`) —
  split evenly. New in this corpus, replacing the language axis as the primary
  balanced covariate. It never enters `rules_engine.label` (temperature bands are
  GSO/regional, not per-country) — it flows through to provenance and lets an
  agent reasoning over a record select the matching `guardrails/` country overlay
  and `gcc_food_law_json/` profile (competent authority, primary statute).

### Overlays — cut across all cells

- `adversarial`: 15% of corpus (~795). Near-boundary excursions, sensor-vs-real
  ambiguity, F/C traps, multi-lot messages.
- `abstention`: 8% of corpus (~424). Genuinely insufficient information.
  Correct output is `insufficient_data`. Never guessable.

---

## 3. Wave sequence

Follow this unless the ledger says a slice is failing badly enough to reorder.

| Wave | Focus |
|---|---|
| 1 | `in_spec` + `door_open`, all products. Pipeline validation. |
| 2 | Remaining three fault modes. Complete the fault axis. |
| 3 | `voice_note` and `qc_form_ocr` emphasis. Artifact axis opens. |
| 4 | Deficit-driven repair. First closed-loop wave. |
| 5 | Adversarial tranche, targeted at the current confusion pairs. |
| 6 | Abstention and insufficient-data. |
| 7 | Deficit-driven repair, round two. |
| 8 | Distribution shift. Rendered by a different model. **Never trained on.** |

---

## 4. How to allocate the 663

Score every cell, then allocate proportionally to score. Do not allocate uniformly.

```
deficit(cell) = 0.45 * count_gap(cell)
              + 0.40 * (1 - f1(cell))
              + 0.15 * staleness(cell)
```

- `count_gap` — normalised shortfall against the 265 target
- `f1` — most recent per-cell disposition F1 from Gate B; treat unmeasured as 0.5
- `staleness` — waves elapsed since the cell last received records, capped at 4

Hard constraints on every plan:
- No cell receives more than 20% of the wave (133 records) in a single wave.
- No cell may exceed its 265 target by more than 5%.
- Every wave carries its proportional share of the adversarial and abstention overlays.
- Artifact-type and jurisdiction balance must hold **within** each cell, not just corpus-wide.

---

## 5. Optimise worst-cell, never mean

The ratchet metric is `worst_cell_f1`. Mean F1 is reported and ignored.

This is deliberate. If you optimise the mean you will discover that generating easy
cells raises it, and you will produce near-duplicate clean cases with an excellent
scorecard and a useless model. Coverage hacking is the expected failure mode of
this role. Optimising the worst cell is the countermeasure.

If two plans have equal expected mean gain, choose the one that lifts the floor.

---

## 6. Reading the logs

Before planning, read in this order:

1. `logs/ledger.jsonl` — one line per completed wave: gate results, per-cell F1,
   what was requested vs what survived screening.
2. `logs/coverage.json` — running fill counts per cell, artifact type, and jurisdiction.
3. `logs/waves/wave_<N-1>/gate_b.json` — the confusion matrix. This tells you which
   *pairs* the model conflates, which is more actionable than which cell scores low.
4. `logs/waves/wave_<N-1>/decisions.md` — the previous rationale and the human note.

Pay particular attention to **survival rate**: requested minus what passed Gate A
(including the `guardrail_violation_rate` check — see `guardrails.py`). A cell with
60% survival is not a data-quantity problem, it is a rendering problem. Requesting
more of it will waste the wave. Flag it instead.

---

## 7. What you must not do

- Do not propose labels, thresholds, or dispositions. The rule engine owns those.
- Do not read the golden set. You receive slice-level aggregates only.
- Do not request a cell that failed Gate A twice running without writing a
  hypothesis for *why* it is failing.
- Do not silently drop a cell because it is hard. Escalate it in the rationale.

---

## 8. Output contract

Write `logs/waves/wave_<N>/plan.json`:

```json
{
  "wave": 4,
  "total": 663,
  "allocations": [
    {"product": "finfish_seafood", "fault_mode": "sensor_artifact",
     "count": 118, "adversarial": 18, "abstention": 9,
     "language_split": {"en": 118},
     "artifact_split": {"logger_csv": 30, "chat_message": 29, "qc_form_ocr": 30, "voice_note": 29},
     "jurisdiction_split": {"AE": 20, "SA": 20, "QA": 20, "KW": 19, "OM": 20, "BH": 19},
     "reason": "worst cell at F1 0.61, confused with compressor_fail, 140 short of target"}
  ],
  "rationale": "Prose. What you are targeting this wave and why.",
  "escalations": ["logger_csv survival rate 62% for frozen_goods in wave 2, renderer suspected"]
}
```

Also append a human-readable summary to `logs/waves/wave_<N>/decisions.md`.
A person will read that file before approving the wave. Write it for them.
