from __future__ import annotations

from cold_chain import guardrails as gr


def test_pack_loads_with_no_problems():
    assert gr.validate_loaded() == []


def test_rule_ids_globally_unique():
    seen = set()
    packs = [gr.base_pack()] + [gr.country_pack(c) for c in gr.COUNTRY_FILES]
    for pack in packs:
        for rule in pack["rules"]:
            assert rule["rule_id"] not in seen, f"duplicate rule_id {rule['rule_id']}"
            seen.add(rule["rule_id"])
    assert len(seen) == 85  # 25 base + 10 * 6 countries, per guardrails/README.md


def test_rules_for_country_includes_base_and_overlay():
    ae_rules = gr.rules_for("AE")
    base_ids = {r["rule_id"] for r in gr.base_pack()["rules"]}
    ae_ids = {r["rule_id"] for r in gr.country_pack("AE")["rules"]}
    got_ids = {r["rule_id"] for r in ae_rules}
    assert base_ids <= got_ids
    assert ae_ids <= got_ids


def test_rule_by_id_found_and_not_found():
    assert gr.rule_by_id("GCC-EDGE-001") is not None
    assert gr.rule_by_id("GCC-EDGE-013")["title"].lower().startswith("frozen chain partial thaw")
    assert gr.rule_by_id("NOT-A-REAL-RULE") is None


def test_temperature_bands_present_and_shaped():
    bands = gr.temperature_bands()
    for name in ("chilled_general", "chilled_fresh_seafood", "frozen", "ambient_stored"):
        assert name in bands
    assert bands["frozen"].max_c == -18
    assert bands["frozen"].refreeze_flag_c == -12
    assert bands["chilled_fresh_seafood"].min_c == 0
    assert bands["chilled_fresh_seafood"].max_c == 4


def test_sentinel_values_include_documented_examples():
    vals = gr.sentinel_values()
    assert -99.9 in vals
    assert -999 in vals
    assert 999 in vals


def test_temperature_sentinel_values_excludes_zero():
    assert 0.0 not in gr.temperature_sentinel_values()
    assert -99.9 in gr.temperature_sentinel_values()


def test_is_sentinel_reading_magnitude_check():
    assert gr.is_sentinel_reading(-99.9) is True
    assert gr.is_sentinel_reading(-60.0) is True  # <= -50
    assert gr.is_sentinel_reading(90.0) is True  # >= 80
    assert gr.is_sentinel_reading(0.0) is False
    assert gr.is_sentinel_reading(2.5) is False
    assert gr.is_sentinel_reading(None) is True


def test_exclude_sentinel_readings():
    clean, excluded = gr.exclude_sentinel_readings([1.0, -99.9, 2.0, 999])
    assert clean == [1.0, 2.0]
    assert excluded == 2


def test_check_artifact_text_detects_metadata_leak():
    hits = gr.check_artifact_text("device=ASSET-1 product_code=finfish_seafood readings: 1,2,3")
    assert any(v.rule_id == "GCC-EDGE-018" for v in hits)


def test_check_artifact_text_detects_expedite_wording():
    hits = gr.check_artifact_text("Given the urgency, we recommend expedite sale of this lot.")
    assert any(v.rule_id == "GCC-EDGE-015" for v in hits)


def test_check_artifact_text_detects_truncated_csv_tail():
    hits = gr.check_artifact_text("2026-07-22 09:", artifact_type="logger_csv")
    assert any(v.rule_id == "GCC-EDGE-002" for v in hits)


def test_check_artifact_text_clean_text_has_no_hits():
    hits = gr.check_artifact_text(
        "Reefer held between 1.1 and 3.2C for the full 24h window, no excursions observed.",
        artifact_type="chat_message",
    )
    assert hits == []
