"""Manual, interactive testing playground. No Mongo, no Azure, no API cost --
every function below is pure and offline, so you can change an input, rerun
one cell, and read the output immediately.

How to use in VS Code:
  1. Install the "Jupyter" extension (Python extension alone also runs cells,
     Jupyter gives you a nicer inline output panel).
  2. Open this file.
  3. Above each block below you'll see "Run Cell" appear as a small link --
     click it, or put your cursor in the cell and press Shift+Enter.
  4. Change any input value in a cell and press Shift+Enter again to see
     the new output. Nothing here needs .env, az login, or Mongo.

Each cell is self-contained: change the input, rerun, read the output.
"""

# %% Setup -- run this cell first
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cold_chain import guardrails as gr
from cold_chain import knowledge_base as kb
from cold_chain.gates import GATE_A, evaluate
from cold_chain.rules_engine import WorldState, label

# %% 1. Rules engine -- a normal in-spec chilled shipment
state = WorldState(
    product="chilled_dairy",
    readings_c=[2.1, 2.4, 2.0, 2.6, 2.3],  # change these numbers
    interval_min=15,
    days_since_production=3,
)
result = label(state)
print(f"disposition:      {result.disposition}")
print(f"rule that fired:   {result.rule_id}")
print(f"peak temperature:  {result.peak_temp_c}")
print(f"excursion minutes: {result.excursion_minutes}")

# %% 2. Rules engine -- push it past the door-open threshold and watch the verdict change
state = WorldState(
    product="chilled_dairy",
    readings_c=[2.1, 6.5, 7.2, 6.8, 7.5, 6.9, 7.1, 6.4],  # several readings over the 5C limit
    interval_min=15,
    days_since_production=3,
)
result = label(state)
print(f"disposition:      {result.disposition}")
print(f"rule that fired:   {result.rule_id}")

# %% 3. Rules engine -- frozen partial thaw (GCC-EDGE-013)
state = WorldState(
    product="frozen_goods",
    readings_c=[-19.0, -18.5, -10.0, -19.2],  # one reading crosses the -12C flag
    interval_min=15,
    days_since_production=30,
)
result = label(state)
print(f"disposition:      {result.disposition}")
print(f"rule that fired:   {result.rule_id}")

# %% 4. Rules engine -- a broken sensor should route to review, not reject
state = WorldState(
    product="finfish_seafood",
    readings_c=[1.0, 1.2, 0.9],
    interval_min=15,
    days_since_production=1,
    sensor_fault=True,  # try flipping this to False and compare
)
result = label(state)
print(f"disposition:      {result.disposition}")
print(f"rule that fired:   {result.rule_id}")

# %% 5. Guardrail scan -- clean, observational text should pass with no hits
text = "Reefer held between 1 and 3 C for the full transit window, no excursions logged."
violations = gr.check_artifact_text(text, artifact_type="chat_message")
print(f"violations found: {len(violations)}")
for v in violations:
    print(f"  {v.rule_id}: {v.detail}")

# %% 6. Guardrail scan -- try text that should get flagged, and see which rule catches it
text = "Temperature spiked but let's expedite sale of this batch before the client notices."
violations = gr.check_artifact_text(text, artifact_type="chat_message")
print(f"violations found: {len(violations)}")
for v in violations:
    print(f"  {v.rule_id}: {v.detail}")

# %% 7. Guardrail scan -- leaked internal metadata (GCC-EDGE-018)
text = "product_code=finfish_seafood cell=chilled|door_open logged normally."
violations = gr.check_artifact_text(text)
print(f"violations found: {len(violations)}")
for v in violations:
    print(f"  {v.rule_id}: {v.detail}")

# %% 8. Knowledge base -- pull the legal citation for any of the six states
citation = kb.citation("AE")  # try "SA", "QA", "KW", "OM", "BH"
print(citation)

# %% 9. Temperature bands -- see the exact numbers the rules engine is built on
for name, band in gr.temperature_bands().items():
    print(f"{name}: min={band.min_c} max={band.max_c}  ({band.basis[:70]}...)")

# %% 10. Gate A -- feed it made-up metrics and see which checks pass or fail
sample_metrics = {
    "schema_validity": 0.998,
    "round_trip_recovery": 0.96,
    "screener_flag_rate": 0.05,
    "near_duplicate_rate": 0.02,
    "cell_fill_deviation": 0.08,
    "max_class_share": 0.40,
    "leakage_probe_acc": 0.55,
    "language_authenticity": 4.1,
    "annotator_kappa": 0.80,
    "guardrail_violation_rate": 0.00,
}
result = evaluate(sample_metrics, GATE_A)
print(f"Gate A passed: {result['passed']}")
for failure in result["failures"]:
    print(f"  FAILED: {failure}")
