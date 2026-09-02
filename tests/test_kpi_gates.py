from __future__ import annotations

from cold_chain.domain import gates, kpi


def test_screener_flag_rate_counts_guardrail_drops():
    rows = [
        {"screener_verdict": "CONSISTENT", "outcome": "kept"},
        {"screener_verdict": "LEAKS_LABEL", "outcome": "dropped_screener"},
        {"screener_verdict": "CONSISTENT", "outcome": "dropped_guardrail"},
    ]
    assert gates.screener_flag_rate(rows) == 2 / 3


def test_near_duplicate_rate_stratified_structured_higher_thresh():
    texts = ["a", "a similar", "b", "b similar"]
    types = ["logger_csv", "logger_csv", "chat_message", "chat_message"]

    def embed(batch: list[str]) -> list[list[float]]:
        out = []
        for t in batch:
            h = hash(t) % 1000 / 1000.0
            out.append([h, 1.0 - h])
        return out

    rate = gates.near_duplicate_rate_stratified(texts, types, embed, default_thresh=0.95, structured_thresh=0.99)
    assert 0.0 <= rate <= 1.0


def test_cell_fill_deviation_survival_adjusted_zero_attempts():
    from cold_chain.domain import catalog as cat

    plan = {"allocations": [{"product": "finfish_seafood", "fault_mode": "in_spec", "count": 10}]}
    cell = cat.cell_key("finfish_seafood", "in_spec")
    kept = {cell: 0}
    attempted = {cell: 0}
    assert gates.cell_fill_deviation_survival_adjusted(plan, kept, attempted) == 1.0


def test_kpi_summarise_twelve_dimensions():
    metrics = {
        "schema_validity": 0.996,
        "round_trip_recovery": 0.96,
        "screener_flag_rate": 0.05,
        "near_duplicate_rate": 0.02,
        "cell_fill_deviation": 0.08,
        "max_class_share": 0.40,
        "leakage_probe_acc": 0.65,
        "language_authenticity": 4.0,
        "annotator_kappa": 0.80,
        "guardrail_violation_rate": 0.005,
    }
    scores = kpi.score_gate_a_metrics(metrics)
    scores += [
        kpi.score_training_readiness(gate_a_passed=True, kept_count=600, export_path=None, preflight_ok=True),
        kpi.score_gate_b_readiness(student_endpoint=True, holdout_count=30, gate_b_ran=False, gate_b_passed=None),
        kpi.score_operational_maturity(
            health_ok=True, ready_ok=True, local_run_exists=True, runbook_exists=True, makefile_targets=True
        ),
    ]
    assert len(scores) == 12
    summary = kpi.summarise(scores)
    assert summary["mean"] >= 7.0


def test_sample_requests_balanced_respects_cap():
    from cold_chain.adapters import logbook as lb_mod
    from cold_chain.cli import runner

    plan = {
        "allocations": [
            {
                "product": "finfish_seafood",
                "fault_mode": "in_spec",
                "count": 20,
                "language_split": {"en": 20},
                "artifact_split": {"chat_message": 20},
                "jurisdiction_split": {"AE": 20},
                "adversarial": 2,
                "abstention": 2,
            },
            {
                "product": "chilled_dairy",
                "fault_mode": "door_open",
                "count": 10,
                "language_split": {"en": 10},
                "artifact_split": {"logger_csv": 10},
                "jurisdiction_split": {"SA": 10},
                "adversarial": 1,
                "abstention": 1,
            },
        ]
    }
    sampled = runner._sample_requests_balanced(plan, wave=1, max_records=15)
    assert len(sampled) == 15
    cells = {lb_mod.cell_key(r.product, r.fault_mode) for r in sampled}
    assert len(cells) == 2
