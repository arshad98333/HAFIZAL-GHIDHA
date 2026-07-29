"""Unit tests for the pure, network-free helper functions in scripts/
(azure_review.py, generate_system_report.py). The network-calling parts of
those scripts are exercised manually against a real Azure OpenAI/Mongo
environment -- see README "Manually running and evaluating a wave" -- not
here."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import azure_review  # noqa: E402
from generate_system_report import _drop_reasons, _fmt_metric_table  # noqa: E402


def test_summarize_reviews_counts_agree_disagree_error():
    results = [
        {"review": {"agrees": True, "concerns": []}},
        {"review": {"agrees": False, "concerns": ["ungrounded"]}},
        {"review": {"error": "boom"}},
        {"review": {"agrees": True, "concerns": ["none"]}},
    ]
    summary = azure_review.summarize_reviews(results)
    assert summary["n"] == 4
    assert summary["agree"] == 2
    assert summary["disagree"] == 1
    assert summary["errored"] == 1
    assert summary["agreement_rate"] == 2 / 4


def test_summarize_reviews_flags_concerns_excludes_errors():
    results = [
        {"review": {"agrees": True, "concerns": ["metadata_leakage"]}},
        {"review": {"error": "boom", "concerns": ["ignored, this is an error row"]}},
    ]
    summary = azure_review.summarize_reviews(results)
    assert len(summary["flagged"]) == 1


def test_summarize_reviews_empty():
    summary = azure_review.summarize_reviews([])
    assert summary["n"] == 0
    assert summary["agreement_rate"] == 0.0


def test_drop_reasons_excludes_kept():
    rows = [
        {"outcome": "kept"}, {"outcome": "kept"},
        {"outcome": "dropped_screener"}, {"outcome": "dropped_screener"}, {"outcome": "dropped_guardrail"},
    ]
    reasons = _drop_reasons(rows)
    assert reasons["dropped_screener"] == 2
    assert reasons["dropped_guardrail"] == 1
    assert "kept" not in reasons


def test_fmt_metric_table_with_checks():
    checks = {"schema_validity": {"value": 0.99, "op": ">=", "bound": 0.995, "passed": False}}
    out = _fmt_metric_table({}, checks)
    assert "schema_validity" in out
    assert "FAIL" in out


def test_fmt_metric_table_without_checks_falls_back_to_bullets():
    out = _fmt_metric_table({"a": 1, "b": 2}, None)
    assert "- `a`: 1" in out
    assert "- `b`: 2" in out


def test_load_from_export_filters_kept_and_respects_limit(tmp_path):
    path = tmp_path / "export.jsonl"
    path.write_text(
        '{"outcome": "kept", "cell": "a"}\n'
        '{"outcome": "dropped_screener", "cell": "b"}\n'
        '{"outcome": "kept", "cell": "c"}\n',
        encoding="utf-8",
    )
    rows = azure_review.load_from_export(path, limit=10)
    assert [r["cell"] for r in rows] == ["a", "c"]

    limited = azure_review.load_from_export(path, limit=1)
    assert len(limited) == 1


def test_extract_text_prefers_output_text():
    class FakeResponse:
        output_text = "hello"

    assert azure_review._extract_text(FakeResponse()) == "hello"


def test_extract_text_falls_back_to_output_structure():
    class FakeContent:
        text = "nested text"

    class FakeItem:
        content = [FakeContent()]

    class FakeResponse:
        output_text = None
        output = [FakeItem()]

    assert azure_review._extract_text(FakeResponse()) == "nested text"


# --------------------------------------------------------------------------- #
# audit_corpus_guardrails.py
# --------------------------------------------------------------------------- #

import audit_corpus_guardrails as audit_mod  # noqa: E402


def _fake_rows() -> list[dict]:
    return [
        {"state_id": "s1", "cell": "finfish_seafood|in_spec", "jurisdiction": "AE",
         "artifact_type": "chat_message", "disposition": "accept", "schema_valid": True,
         "round_trip_ok": True, "screener_verdict": "CONSISTENT", "confidence": 0.9,
         "rendered_text": "Reefer held 1-3C, no excursions."},
        {"state_id": "s2", "cell": "finfish_seafood|door_open", "jurisdiction": "SA",
         "artifact_type": "logger_csv", "disposition": "hold_for_qa", "schema_valid": True,
         "round_trip_ok": True, "screener_verdict": "CONSISTENT", "confidence": 0.8,
         "rendered_text": "device=ASSET-1 product_code=finfish_seafood\n1,2"},
        {"state_id": "s3", "cell": "frozen_goods|compressor_fail", "jurisdiction": "QA",
         "artifact_type": "voice_note", "disposition": "expedite_sale", "schema_valid": True,
         "round_trip_ok": True, "screener_verdict": "CONSISTENT", "confidence": 0.5,
         "rendered_text": "we recommend expedite sale of this batch"},
    ]


def test_audit_records_counts_and_invariant():
    audit = audit_mod.audit_records(_fake_rows())
    assert audit["n"] == 3
    assert len(audit["violations"]) == 2  # s2 (metadata leak) + s3 (expedite wording)
    assert len(audit["expedite_sale_hits"]) == 1
    assert audit["expedite_sale_hits"][0]["state_id"] == "s3"
    assert audit["by_cell"]["finfish_seafood|in_spec"]["n"] == 1
    assert audit["by_jurisdiction"]["SA"]["violations"] == 1
    assert audit["disposition_counts"]["expedite_sale"] == 1


def test_audit_records_empty():
    audit = audit_mod.audit_records([])
    assert audit["n"] == 0
    assert audit["violation_rate"] == 0.0
    assert audit["mean_confidence"] is None


def test_render_report_includes_invariant_violation():
    audit = audit_mod.audit_records(_fake_rows())
    report = audit_mod.render_report(audit, "test scope")
    assert "VIOLATED" in report
    assert "s3" in report
    assert "GCC-EDGE-018" in report


def test_load_from_export_defaults_to_kept_only(tmp_path):
    path = tmp_path / "export.jsonl"
    path.write_text(
        '{"outcome": "kept", "cell": "a"}\n'
        '{"outcome": "dropped_screener", "cell": "b"}\n',
        encoding="utf-8",
    )
    rows = audit_mod.load_from_export(path)
    assert [r["cell"] for r in rows] == ["a"]


def test_write_csv_writes_one_row_per_violation(tmp_path):
    audit = audit_mod.audit_records(_fake_rows())
    out = tmp_path / "out.csv"
    audit_mod.write_csv(audit, out)
    content = out.read_text(encoding="utf-8")
    assert "state_id" in content.splitlines()[0]
    assert len(content.splitlines()) == 1 + len(audit["violations"])


# --------------------------------------------------------------------------- #
# live_stream_demo.py
# --------------------------------------------------------------------------- #

import live_stream_demo as stream_mod  # noqa: E402


def test_run_stream_counts_violations_and_dispositions():
    import asyncio

    result = asyncio.run(stream_mod.run_stream(_fake_rows(), delay=0.0, verbose_flags=False))
    assert result["n"] == 3
    assert result["violations"] == 2
    assert result["dispositions"]["expedite_sale"] == 1
    assert result["throughput_per_s"] > 0


def test_run_stream_handles_empty_list():
    import asyncio

    result = asyncio.run(stream_mod.run_stream([], delay=0.0, verbose_flags=False))
    assert result["n"] == 0
    assert result["violations"] == 0
