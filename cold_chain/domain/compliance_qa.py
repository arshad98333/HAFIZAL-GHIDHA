"""Retrieval and prompt-chain construction for the compliance Q&A chat
(``/compliance/ask``).

This module exists because of one hard constraint: this repository's whole
design philosophy is that no disposition label is ever LLM-generated
(``rules_engine.py`` module docstring) -- every threshold traces to a cited
source. A free-form "ask anything" chat breaks that discipline by
construction unless it is deliberately re-imposed here: the model is never
handed the question raw. It is handed only the guardrail rules and law
citations this repository actually contains, and is explicitly instructed to
say so, rather than invent a plausible-sounding clause, when the user's
question references something the pack does not contain.

That last case is not hypothetical -- it is the common one. A question like
"the GSO clause allows variance for unavoidable technical operations, is
this a violation?" cites a clause that does not exist anywhere in
``guardrails/`` or ``gcc_food_law_json/`` (checked by grep across both at the
time this module was written). A grounded chat has to be able to say that
plainly instead of confabulating a citation number, or it is worse than no
chat at all for a compliance tool.

Retrieval here is deliberately simple: keyword/jurisdiction/product overlap
scoring over the guardrail pack and the knowledge-base citation for the
named jurisdiction, not embeddings -- there is no vector index in this repo
yet (see DEVELOPER_PRD.md's `rag_retrieval` node, which is a *different*,
unbuilt project). If question volume or precision ever demands it, this is
the place to swap in an embedding-based retriever without touching the
prompt-chain shape below.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

# Every rule_id in the guardrail pack matches this shape: a 2-letter country
# code or "GCC", then EDGE or NORM, then a zero-padded number -- see
# guardrails/README.md. Used by evaluate_citations() below to find every
# rule ID the model *claims* to cite, so it can be checked against what was
# actually retrieved.
_RULE_ID_PATTERN = re.compile(r"\b(?:GCC|AE|SA|QA|KW|OM|BH)-(?:EDGE|NORM)-\d{3}\b")

from . import guardrails as gr
from . import knowledge_base as kb
from .catalog import JURISDICTIONS, PRODUCTS
from .rules_engine import SPECS

# A GSO (GCC Standardization Organization) instrument code, e.g. "GSO 150-1",
# "GSO 9", "GSO 2500". Used by evaluate_citations() below for the same
# fabrication check as _RULE_ID_PATTERN, extended to standards clauses --
# the recurring real-world failure mode this module was written against is
# a *GSO* citation the model invents ("the GSO clause allows variance for
# unavoidable technical operations"), not just an invented GCC-EDGE rule ID.
_GSO_CODE_PATTERN = re.compile(r"\bGSO\s*(\d+(?:-\d+)?)\b", re.IGNORECASE)


@lru_cache(maxsize=1)
def _known_gso_codes() -> frozenset[str]:
    """Every GSO standard number that actually appears anywhere in this
    repo's grounding data: the guardrail pack (base file + all six country
    overlays -- temperature-band ``basis`` text, rule fields) and the six
    ``gcc_food_law_json`` country profiles (``standards_framework.key_standards``
    codes, legal-framework citation text). This is deliberately repo-wide,
    not scoped to one query's retrieved context -- a GSO instrument number is
    a fact about GCC food law, not something invented per-question, so the
    fabrication check is "does this number appear anywhere in the law/
    guardrail data we actually loaded", exactly mirroring the discipline
    ``evaluate_citations`` already applies to GCC-EDGE/... rule IDs.

    Computed once via a JSON-dump-and-regex sweep rather than reaching into
    each file's schema by hand, so this does not silently go stale if a new
    ``key_standards`` entry or guardrail field is added later -- anywhere a
    GSO code appears in the loaded data is picked up.
    """
    blobs: list[str] = [json.dumps(gr.base_pack())]
    for code in JURISDICTIONS:
        blobs.append(json.dumps(gr.country_pack(code)))
        try:
            blobs.append(json.dumps(kb.profile(code)))
        except kb.KnowledgeBaseError:
            continue
    haystack = "\n".join(blobs)
    return frozenset(m.group(1).upper() for m in _GSO_CODE_PATTERN.finditer(haystack))

# -- retrieval -------------------------------------------------------------- #

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "this", "that", "to", "of",
    "in", "on", "for", "and", "or", "but", "does", "do", "did", "can", "it",
    "its", "shows", "during", "mins", "min", "minutes", "with", "at", "by",
    "as", "be", "if", "so", "not",
}


def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z]{3,}", text.lower()) if w not in _STOPWORDS}


# Keyword hints for inferring a product from free text when it disagrees with
# (or is more specific than) whatever the caller/UI passed in. This exists
# because the UI's product selector is an independent form field the user
# can leave stale -- e.g. asking about a frozen-food defrost cycle while the
# dropdown still says "table_eggs" from a previous question. Silently
# retrieving the wrong product's temperature band (and letting the model
# reason against it) is worse than either using the question's own wording
# or telling the user about the mismatch -- so retrieve() does the latter.
_PRODUCT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "frozen_goods": ("frozen", "freezer", "defrost", "refreeze", "thaw"),
    "finfish_seafood": ("fish", "seafood", "finfish", "shrimp", "prawn"),
    "chilled_dairy": ("dairy", "milk", "yogurt", "yoghurt", "cheese", "cream"),
    "table_eggs": ("egg", "eggs"),
}


def _infer_product(question: str) -> str | None:
    lowered = question.lower()
    for prod, keywords in _PRODUCT_KEYWORDS.items():
        if any(re.search(rf"\b{kw}\b", lowered) for kw in keywords):
            return prod
    return None


@dataclass
class RetrievedContext:
    jurisdiction: str | None
    product: str | None
    rules: list[dict[str, Any]]
    citation: kb.LegalCitation | None
    product_spec_text: str | None
    unmatched_query_terms: set[str] = field(default_factory=set)
    requested_product: str | None = None
    product_mismatch: bool = False

    def is_empty(self) -> bool:
        return not self.rules and self.citation is None and self.product_spec_text is None


def _score_rule(rule: dict[str, Any], query_terms: set[str]) -> int:
    haystack = " ".join(
        [
            rule.get("title", ""),
            rule.get("category", ""),
            rule.get("escalation", ""),
            " ".join(rule.get("agent_must", [])),
            " ".join(rule.get("agent_must_not", [])),
        ]
    )
    return len(query_terms & _tokenize(haystack))


def retrieve(question: str, jurisdiction: str | None = None, product: str | None = None, top_k: int = 6) -> RetrievedContext:
    """Best-effort keyword retrieval over the guardrail pack, scoped to a
    jurisdiction if one is given (or mentioned in the question) and scored
    against the question's own terms. Always includes the base (GCC-wide)
    rules pool plus the jurisdiction overlay, never just one."""
    juris = (jurisdiction or "").upper() or None
    if juris and juris not in JURISDICTIONS:
        juris = None
    if juris is None:
        for code in JURISDICTIONS:
            if re.search(rf"\b{code}\b", question, re.IGNORECASE):
                juris = code
                break

    requested_prod = product if product in PRODUCTS else None
    inferred_prod = _infer_product(question)
    # The question's own wording wins over a stale/mismatched dropdown value:
    # a keyword match in free text is a stronger, more specific signal than a
    # form field the user may not have updated. If they agree, or nothing was
    # inferred, use whatever was requested.
    prod = inferred_prod if (inferred_prod and inferred_prod != requested_prod) else requested_prod
    product_mismatch = bool(requested_prod and inferred_prod and inferred_prod != requested_prod)

    query_terms = _tokenize(question)
    all_rules = gr.rules_for(juris)
    scored = sorted(all_rules, key=lambda r: _score_rule(r, query_terms), reverse=True)
    top_scored = [r for r in scored[: top_k * 2] if _score_rule(r, query_terms) > 0][:top_k]
    # Always surface at least the base commercial-pressure / disposition-vocabulary
    # guardrail (GCC-EDGE-015) even on a zero-match question -- it is the single
    # most load-bearing rule for "is this a violation" style questions and should
    # not depend on the user's exact wording.
    if not any(r["rule_id"] == "GCC-EDGE-015" for r in top_scored):
        anchor = gr.rule_by_id("GCC-EDGE-015")
        if anchor:
            top_scored = ([anchor] + top_scored)[:top_k]

    citation = None
    if juris:
        try:
            citation = kb.citation(juris)
        except kb.KnowledgeBaseError:
            citation = None

    spec_text = None
    if prod and prod in SPECS:
        spec = SPECS[prod]
        band = f"{spec.temp_min_c}–{spec.temp_max_c}°C" if spec.temp_min_c is not None else f"≤{spec.temp_max_c}°C"
        spec_text = (
            f"{prod} ({spec.regime}): band {band}; hold_for_qa threshold "
            f"{spec.max_excursion_min} cumulative minutes out of band; reject threshold "
            f"{spec.reject_excursion_min} minutes; shelf life {spec.shelf_life_days} days; "
            f"basis: {spec.clause}."
            + (f" Refreeze flag: {spec.refreeze_flag_c}°C (GCC-EDGE-013)." if spec.refreeze_flag_c is not None else "")
        )

    matched_terms: set[str] = set()
    for r in top_scored:
        matched_terms |= query_terms & _tokenize(r.get("title", ""))

    return RetrievedContext(
        jurisdiction=juris,
        product=prod,
        rules=top_scored,
        citation=citation,
        product_spec_text=spec_text,
        unmatched_query_terms=query_terms - matched_terms,
        requested_product=requested_prod,
        product_mismatch=product_mismatch,
    )


def format_context_block(ctx: RetrievedContext) -> str:
    """The only law/guardrail text the model is allowed to cite from. Every
    step prompt embeds this verbatim and is told, in each step's own system
    prompt, that citing anything outside it is a fabrication."""
    lines: list[str] = []
    if ctx.citation:
        lines.append(
            f"JURISDICTION: {ctx.citation.country} ({ctx.jurisdiction}) — "
            f"primary instrument: {ctx.citation.instrument}; "
            f"regulator: {ctx.citation.authority} ({ctx.citation.authority_abbreviation})."
        )
    elif ctx.jurisdiction:
        lines.append(f"JURISDICTION: {ctx.jurisdiction} (no citation record loaded).")
    else:
        lines.append("JURISDICTION: not specified by the user — do not assume one.")

    if ctx.product_spec_text:
        lines.append(f"PRODUCT SPEC (deterministic, from the rules engine): {ctx.product_spec_text}")

    if ctx.rules:
        lines.append("\nRETRIEVED GUARDRAIL RULES (this is the ENTIRE set you may cite — nothing else exists):")
        for r in ctx.rules:
            lines.append(
                f"- [{r['rule_id']}] {r['title']} (severity: {r.get('severity', 'n/a')})\n"
                f"  agent_must: {'; '.join(r.get('agent_must', [])) or 'n/a'}\n"
                f"  agent_must_not: {'; '.join(r.get('agent_must_not', [])) or 'n/a'}\n"
                f"  escalation: {r.get('escalation', 'n/a')}"
            )
    else:
        lines.append("\nRETRIEVED GUARDRAIL RULES: none matched this question.")

    return "\n".join(lines)


# -- 4-step prompt chain ------------------------------------------------------ #

STEP_INTENT = "intent_extraction"
STEP_CONSTRAINTS = "constraint_mapping"
STEP_COUNTERFACTUAL = "counterfactual_analysis"
STEP_SYNTHESIS = "final_synthesis"

STEPS: tuple[tuple[str, str], ...] = (
    (STEP_INTENT, "Intent Extraction & Law Anchoring"),
    (STEP_CONSTRAINTS, "Constraint & Variable Mapping"),
    (STEP_COUNTERFACTUAL, "Strategic Counterfactual Analysis"),
    (STEP_SYNTHESIS, "Final Recommendation Synthesis"),
)

_BASE_SYSTEM = (
    "You are a GCC cold-chain compliance reasoning assistant (GSO-aligned, "
    "covering Saudi Arabia, UAE, Qatar, Bahrain, Kuwait, and Oman). You are "
    "one step in a 4-step chain; only produce this step's output, not the "
    "others. Hard rules that apply to every step: (1) You may cite ONLY the "
    "rule IDs, thresholds, and jurisdiction/authority names given to you in "
    "the CONTEXT block. (2) If the user's question references a clause, "
    "exemption, or provision that is NOT in the CONTEXT block, you must say "
    "explicitly that it is not present in the loaded guardrail/law pack and "
    "cannot be verified — never invent a plausible-sounding clause number "
    "or provision to fill the gap. (3) Never recommend or imply "
    "'expedite_sale' or any variant of releasing product under commercial "
    "pressure — GCC-EDGE-015: commercial pressure never converts an "
    "excursion into a release. (4) This is decision-support, not legal "
    "advice; a licensed QA/compliance authority makes the final call."
)


def build_step_messages(
    step_id: str,
    *,
    question: str,
    context_block: str,
    prior_outputs: dict[str, str],
) -> list[dict[str, str]]:
    """Each step is a fresh, independently-run K2 call (not a single
    multi-section completion) so the UI's 4 nodes reflect 4 real reasoning
    passes, each conditioned on the previous step's actual output."""
    history = "\n\n".join(
        f"--- {title} (already completed) ---\n{prior_outputs[sid]}"
        for sid, title in STEPS
        if sid in prior_outputs
    )
    header = f"USER QUESTION:\n{question}\n\nCONTEXT:\n{context_block}"
    if history:
        header += f"\n\n{history}"

    if step_id == STEP_INTENT:
        instruction = (
            "STEP 1 — Intent Extraction & Law Anchoring. Identify: (a) what "
            "the user is actually asking (a violation determination? a "
            "disposition recommendation? a factual lookup?); (b) the "
            "product/regime and jurisdiction implied or stated; (c) which "
            "retrieved rule IDs and/or the citation, if any, actually anchor "
            "this question. Explicitly flag any clause or exemption the user "
            "mentions that is NOT in CONTEXT. Be concise — this is scoping, "
            "not the answer."
        )
    elif step_id == STEP_CONSTRAINTS:
        instruction = (
            "STEP 2 — Constraint & Variable Mapping. List the concrete, "
            "numeric constraints in play from CONTEXT (temperature band, "
            "excursion-minute thresholds for hold_for_qa vs reject, shelf "
            "life, sensor-fault handling, sentinel-value handling) and map "
            "the user's stated scenario variables (temperatures, durations, "
            "conditions they describe) against each one. Where a variable "
            "the scenario needs is missing or ambiguous, say so explicitly "
            "rather than assuming a value."
        )
    elif step_id == STEP_COUNTERFACTUAL:
        instruction = (
            "STEP 3 — Strategic Counterfactual Analysis. Explore how the "
            "assessment would change under plausible alternative framings: "
            "e.g. if this were logged as a sensor artifact instead of a "
            "genuine reading (GCC-EDGE guardrails on sentinel values), if "
            "the excursion crossed the hold vs reject threshold, if this is "
            "closer to end-of-shelf-life, or if the user's claimed exemption "
            "were real vs. absent from the pack. Be explicit about which "
            "counterfactual the retrieved rules actually support and which "
            "are speculative."
        )
    else:
        instruction = (
            "STEP 4 — Final Recommendation Synthesis. Give a direct answer: "
            "state the most defensible disposition-style conclusion (or "
            "'insufficient information' / 'requires QA/legal review' if "
            "that is the honest answer) given ONLY what steps 1–3 "
            "established. Cite the specific rule ID(s) or citation you are "
            "relying on. If the user's claimed clause/exemption was flagged "
            "in step 1 as absent from CONTEXT, restate that plainly here as "
            "part of the answer — do not let it quietly resurface as if it "
            "were confirmed. Close with the standard disclaimer that this is "
            "decision support, not a legal ruling."
        )

    return [
        {"role": "system", "content": _BASE_SYSTEM},
        {"role": "user", "content": f"{header}\n\n{instruction}"},
    ]


# -- deterministic citation-fidelity eval ------------------------------------ #
#
# This is the one automated check run on every K2 answer, and it costs no
# extra model call: after the 4-step chain finishes, extract every rule-ID-
# shaped token the model actually wrote in its final answer and diff it
# against the rule IDs that were genuinely retrieved and handed to it in
# CONTEXT. Anything cited that wasn't in CONTEXT is either a real error
# (the model misquoted an ID that *was* given to it) or a fabrication (an ID
# invented outright) -- both are worth surfacing, since the whole point of
# the grounding in `retrieve()` is that nothing gets cited that wasn't
# actually loaded from `guardrails/`.
#
# This is deliberately not an LLM-judge pass (no self-consistency voting,
# no second K2 call) -- K2's low RPM ceiling means every extra call has a
# real latency/availability cost, and a regex diff against ground truth we
# already hold is strictly more reliable than asking a model to grade
# itself for this specific, mechanically-checkable property.


@dataclass
class CitationEval:
    cited_rule_ids: list[str]
    verified_rule_ids: list[str]
    unverified_rule_ids: list[str]
    cited_gso_codes: list[str] = field(default_factory=list)
    verified_gso_codes: list[str] = field(default_factory=list)
    unverified_gso_codes: list[str] = field(default_factory=list)

    @property
    def all_verified(self) -> bool:
        return not self.unverified_rule_ids and not self.unverified_gso_codes

    def to_dict(self) -> dict[str, Any]:
        return {
            "cited_rule_ids": self.cited_rule_ids,
            "verified_rule_ids": self.verified_rule_ids,
            "unverified_rule_ids": self.unverified_rule_ids,
            "cited_gso_codes": self.cited_gso_codes,
            "verified_gso_codes": self.verified_gso_codes,
            "unverified_gso_codes": self.unverified_gso_codes,
            "all_verified": self.all_verified,
        }


def evaluate_citations(answer_text: str, ctx: RetrievedContext) -> CitationEval:
    """Cross-checks every rule ID *and* every "GSO ###" clause number the
    model cited in its final answer against, respectively, the rule IDs
    actually present in the retrieved CONTEXT it was given, and the full set
    of GSO instrument numbers this repository's law/guardrail data actually
    contains (see ``_known_gso_codes``). An empty ``unverified_rule_ids`` and
    ``unverified_gso_codes`` is the signal a reviewer (or the UI) should look
    for; a non-empty one means the model referenced a rule ID or a GSO
    standard number that isn't grounded in data this repository actually
    loaded, and the answer should be treated as suspect until a human checks
    it directly. The GSO check exists because of a real failure mode this
    module was written against: a user asking about a "GSO clause" that
    allows some convenient exemption which simply does not exist in
    ``guardrails/`` or ``gcc_food_law_json/`` -- the model must say so, not
    invent a plausible-sounding "GSO 150-3" to agree with the user."""
    cited = sorted(set(_RULE_ID_PATTERN.findall(answer_text)))
    retrieved_ids = {r["rule_id"] for r in ctx.rules}
    verified = [rid for rid in cited if rid in retrieved_ids]
    unverified = [rid for rid in cited if rid not in retrieved_ids]

    cited_gso = sorted({m.group(1).upper() for m in _GSO_CODE_PATTERN.finditer(answer_text)})
    known_gso = _known_gso_codes()
    verified_gso = [code for code in cited_gso if code in known_gso]
    unverified_gso = [code for code in cited_gso if code not in known_gso]

    return CitationEval(
        cited_rule_ids=cited,
        verified_rule_ids=verified,
        unverified_rule_ids=unverified,
        cited_gso_codes=cited_gso,
        verified_gso_codes=verified_gso,
        unverified_gso_codes=unverified_gso,
    )
