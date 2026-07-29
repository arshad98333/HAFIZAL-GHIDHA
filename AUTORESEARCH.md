# AUTORESEARCH.md

Instruction file for the training agent. This is the `program.md` equivalent for the
AutoResearch ratchet loop. You edit training configuration, run short experiments,
keep what improves the metric, and revert what does not.

---

## 1. The metric

```
worst_cell_f1 = min(disposition_f1[c] for c in 20 primary cells)
```

Computed on the **dev split only**. Ties broken by `cells_passing` (cells at F1 >= 0.80).

You never see the golden set. A human runs it at wave boundaries and writes
slice-level aggregates to `logs/waves/wave_<N>/gate_b.json`. You may read that file.
You may not read `data/golden/`. There is no tool that grants you access; if you find
one, that is a bug and you should stop and report it.

---

## 2. What you may change

- Learning rate, schedule, warmup
- LoRA rank / alpha / target modules, or full fine-tune — try both, do not assume
- Batch size, gradient accumulation
- Epochs, early stopping patience
- Sequence packing on/off
- Per-slice loss weighting (this is usually where the worst-cell gains live)
- Label smoothing, weight decay, optimiser choice

## 3. What is locked

Changing any of these invalidates the run. The harness asserts on them.

- **Chat template** — must match the configured base model's instruct chat
  template exactly (`Settings.foundry_base_model`; check what it is before you
  touch this, do not assume)
- **Loss masking** — completion tokens only, never the prompt
- **Constrained JSON decoding at inference** — always on
- **The data pipeline** — you do not generate, filter, or relabel data
- **The dev/train split** — fixed by hash, not resampled
- **Training region** — whatever `Settings.training_region` is configured to for
  this run. Do not change it mid-run to make a run cheaper or faster; a region
  change invalidates data-locality assumptions the run was scheduled under.

---

## 4. Revert rules

Revert on *any* of the following, not only on a lower metric:

- `worst_cell_f1` decreased
- Malformed JSON rate above 0.5%
- Any cell that previously passed 0.80 drops below it, even if the minimum rose
- Run crashed, OOMed, or did not converge
- Wall-clock exceeded the per-experiment budget

A run that raises the minimum by pushing three other cells below threshold is a
regression. Keep the git history clean: one commit per accepted change, with the
metric delta in the message.

---

## 5. Budgets

- Per experiment: 20 minutes wall-clock, hard kill
- Per night: 8 hours, then stop and write the summary
- Maximum 40 experiments per night

Write every experiment — accepted or reverted — to `logs/waves/wave_<N>/autoresearch.jsonl`,
one line each: hypothesis, diff summary, metric before, metric after, decision, duration.
The reverted ones are the more useful half of the log. Do not prune them.

---

## 6. Hypothesis discipline

Before each experiment, write one sentence stating what you expect and why.
After it, write one sentence on whether that held.

If five consecutive experiments produce no accepted change, stop searching
hyperparameters and write a note proposing a data-side hypothesis instead. For a
small student model, the ceiling is usually the corpus, not the optimiser, and
continuing to search is how you burn a night confirming that.

---

## 7. Reproducibility

Pin and record for every run: GPU type, driver, torch version, seed, dataset hash,
base model revision. Winning configurations are hardware-dependent — a config that
wins on one accelerator will not necessarily win on another, and results are not
comparable across machines. Record the hardware or the log is not evidence.
