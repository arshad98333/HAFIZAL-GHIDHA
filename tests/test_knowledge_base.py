from __future__ import annotations

import pytest

from cold_chain import knowledge_base as kb


def test_all_jurisdictions_load_with_no_problems():
    assert kb.validate_loaded() == []


def test_jurisdictions_are_six_gcc_states():
    assert set(kb.JURISDICTIONS) == {"AE", "SA", "QA", "KW", "OM", "BH"}
    assert len(kb.JURISDICTIONS) == 6


@pytest.mark.parametrize("code", ["AE", "SA", "QA", "KW", "OM", "BH"])
def test_citation_populated_for_every_jurisdiction(code):
    c = kb.citation(code)
    assert c.jurisdiction == code
    assert c.instrument != "unspecified"
    assert c.authority != "unspecified"


def test_citation_rejects_unknown_jurisdiction():
    with pytest.raises(kb.KnowledgeBaseError):
        kb.citation("ZZ")


def test_profile_has_required_schema_keys():
    required = set(kb.schema()["required"])
    prof = kb.profile("AE")
    assert required <= prof.keys()


def test_all_profiles_distinct_countries():
    names = {kb.profile(c)["meta"]["country"] for c in kb.JURISDICTIONS}
    assert len(names) == 6
