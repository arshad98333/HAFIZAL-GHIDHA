from __future__ import annotations

from cold_chain import gates


def test_guardrail_violation_rate_empty():
    assert gates.guardrail_violation_rate([]) == 0.0


def test_guardrail_violation_rate_mixed():
    texts = [
        "Reefer held 1-3C for the transit, no issues.",
        "product_code=finfish_seafood readings look fine",
        "we recommend expedite sale immediately",
    ]
    rate = gates.guardrail_violation_rate(texts)
    assert rate == 2 / 3


def test_evaluate_reports_missing_metric_as_failure():
    result = gates.evaluate({}, {"schema_validity": (">=", 0.995)})
    assert result["passed"] is False
    assert "schema_validity: not measured" in result["failures"]


def test_evaluate_passes_when_all_bounds_hold():
    result = gates.evaluate(
        {"a": 0.99, "b": 0.01, "c": 0.5},
        {"a": (">=", 0.9), "b": ("<=", 0.05), "c": ("between", (0.0, 1.0))},
    )
    assert result["passed"] is True


def test_max_class_share_empty_labels():
    assert gates.max_class_share([]) == 1.0


def test_max_class_share_uniform():
    assert gates.max_class_share(["a", "b", "a", "b"]) == 0.5


def test_ratchet_ok_first_wave_always_ok():
    from collections import Counter

    slices = gates.summarise_slices({"cellA": 0.7}, Counter())
    ok, why = gates.ratchet_ok(slices, None)
    assert ok is True


def test_ratchet_rejects_worst_cell_regression():
    from collections import Counter

    prev = gates.summarise_slices({"cellA": 0.8, "cellB": 0.9}, Counter())
    current = gates.summarise_slices({"cellA": 0.7, "cellB": 0.95}, Counter())
    ok, why = gates.ratchet_ok(current, prev)
    assert ok is False


def test_ratchet_rejects_dropped_passing_cell_even_if_floor_rises():
    from collections import Counter

    prev = gates.summarise_slices({"cellA": 0.6, "cellB": 0.85}, Counter())
    current = gates.summarise_slices({"cellA": 0.65, "cellB": 0.79}, Counter())
    ok, why = gates.ratchet_ok(current, prev)
    assert ok is False
