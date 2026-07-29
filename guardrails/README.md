# Perishable & Cold-Storage Guardrails for AI Agents — GCC

**Version 1.0.0 · 28 July 2026 · 85 rules across 7 files**

Guardrails for an AI agent that ingests cold-chain telemetry (logger CSV) or operator narrative (chat message) for perishable consignments in the six GCC states and proposes a disposition. Built from your six country food-law profiles in `../gcc_food_law_json/` and the failure modes in `wave_9001.jsonl`.

## Files

| File | Rules | Split |
|---|---|---|
| `00_gcc_base_guardrails.json` | 25 | 20 edge / 5 normal |
| `01_uae_cold_chain_guardrails.json` | 10 | 8 edge / 2 normal |
| `02_saudi_arabia_cold_chain_guardrails.json` | 10 | 8 edge / 2 normal |
| `03_qatar_cold_chain_guardrails.json` | 10 | 8 edge / 2 normal |
| `04_kuwait_cold_chain_guardrails.json` | 10 | 8 edge / 2 normal |
| `05_oman_cold_chain_guardrails.json` | 10 | 8 edge / 2 normal |
| `06_bahrain_cold_chain_guardrails.json` | 10 | 8 edge / 2 normal |

**Pareto split verified: 68 edge / 17 normal = exactly 80.0% edge.** Every file holds the ratio individually, and each country file holds it when merged with the base (28 edge / 7 normal). Rule IDs are globally unique with no collisions.

Load order: base first, then the country overlay. **The overlay wins on conflict.**

## Rule object shape

```
rule_id · class · category · title · severity
trigger { expression, signals }
agent_must[] · agent_must_not[]
escalation
legal_basis { instrument, authority }      ← country files
derived_from { wave9001_cell, evidence }   ← where the rule came from
worked_example { input, wrong, correct }   ← on the highest-value rules
```

Severity `blocking` means the rule halts the disposition path. 48 of the 85 rules are blocking.

## What wave_9001 actually taught the pack

Ten records, one cargo type (`finfish_seafood`), five failure cells, two artifact types, two languages. The interesting part isn't the temperature physics — it's everything wrapped around it.

**The provenance finding dominates everything else.** All ten records carry `generator_model: synthetic-physics-v1`. All ten were dropped by the pipeline (7 `dropped_screener`, 3 `dropped_roundtrip`). None has `human_reviewed: true`. `round_trip_ok` is `false` or `null` throughout. An agent that quietly dispositioned these would be wrong ten times out of ten on provenance alone, before touching a single temperature reading. That's `GCC-EDGE-020`, and it can't be overridden by an instruction inside the artifact.

**Every logger CSV is truncated.** Each one ends mid-line — `2026-07-22 09:`, `2026-07-26T07:` — timestamp cut, temperature field absent. An agent reading the last complete row as "the final temperature" gets it wrong on all five. `GCC-EDGE-002`.

**One record asks for `expedite_sale` on a load with spikes to 17.32 °C and 14.35 °C**, ambient 37.3 °C, three days since production. That is the most dangerous single row in the dataset, and it produced the pack's hardest rule: `GCC-EDGE-015` removes `expedite_sale` from the agent's action space entirely.

**One in-spec record is labelled `reject`** (0.8–3.03 °C across 36 readings). Nothing in the telemetry supports it. The agent must not invent a justification, and must not overwrite the label either — it names the gap and returns it. `GCC-EDGE-017`. The counterpart is `GCC-EDGE-016`, from a door-open record whose CSV shows no excursion at all: narrative and telemetry contradict, so neither can carry an accept.

**Two records are screened `LEAKS_LABEL`** — the CSV header embeds `product_code=finfish_seafood` and the record envelope carries the cell name, which encodes the ground-truth failure mode. `GCC-EDGE-018` forbids reading metadata, filenames or scenario labels as evidence. `product_code` selects the temperature band and nothing else.

**A `-99.9` sentinel** appears in the Arabic sensor-artifact narrative. Averaged in, it makes a warm chain look cold. `GCC-EDGE-001`.

**Device IDs collide.** `GCC-RF-18472` appears against both `ASSET-771904` and `ASSET-771204`. Either one logger served two consignments or an ID was mistyped — both disqualify an autonomous accept. `GCC-EDGE-004`.

**Timestamps are inconsistent within one cargo type** — naive local (`2026-07-22 00:00`) alongside explicit UTC (`2026-07-25T00:00:00Z`). In a region split across UTC+3 and UTC+4, a silent assumption is a 3–4 hour error. `GCC-EDGE-005`.

**Five of ten records are Arabic MSA**, using `°م` and hedge words like `أغلبها` ("most of them") and `حوالي` ("approximately"). Those hedges sit directly next to the excursions they obscure. Every country file carries a bilingual rule requiring the upper bound of an approximate range, never the midpoint, and verbatim Arabic in the evidence trail.

**The three excursion signatures are physically distinct** and must not be collapsed: door-open (isolated spikes, fast recovery, `GCC-EDGE-009`), setpoint drift (slow ramp into 6.3–6.9 °C, `GCC-EDGE-011`), compressor failure (monotonic rise to 9.92 °C still climbing at end of log, `GCC-EDGE-010`). Only the third is an unresolved active failure.

**Log windows span 7.5–9 hours. Narratives report 0–7 days since production.** A 9-hour log cannot evidence a 7-day chain — at worst, 4.5% coverage. `GCC-EDGE-006`.

## The country layer

Each overlay covers the same eight edge themes, but the content diverges sharply because the legal regimes do.

**Kuwait has the sharpest single rule in the pack.** Under MR 6/2023 Article 64(2), moving a PAFN-seized consignment without prior permission carries KWD 2,000–5,000 plus possible activity suspension. So when a detained reefer starts failing, the intuitive action — move it somewhere colder — is the penalised one. `KW-EDGE-001` forces urgent PAFN contact instead. Kuwait also makes record retention itself an offence to breach (KWD 100–1,000), so retaining the raw telemetry artifact is a legal duty there, not just hygiene.

**Oman is where your dataset lands hardest.** `wave_9001` is entirely finfish/seafood, and Omani seafood falls to the Fish Quality Control Centre under Ministerial Decree 12/2009 — not general food control. An excursion on an export consignment can jeopardise Oman's EU, EAEU and US market-access arrangements, not just the load. `OM-EDGE-002`. Separately, `OM-EDGE-001` exists purely because your supplied Oman PDF puts the FSQC under the wrong ministry.

Oman also has `OM-EDGE-003`: under the 2025 Article 30 bis amendment, a pattern of excursions traced to one foreign facility can trigger an FSQC audit of that facility's HACCP system in the country of origin — at the importer's or exporter's cost. That makes facility-level excursion history a compliance asset, not just an ops metric.

**Saudi Arabia** blocks on FASEH: no imported consignment releases before SFDA approval, however good the telemetry looks (`SA-EDGE-002`). Halal certificates only count if the issuing body is recognised by the SFDA Halal Center.

**UAE** is the only jurisdiction where the governing local authority changes mid-journey, and free zones are expressly in scope under Article 19 (`AE-EDGE-002`).

**Qatar** is multi-agency, so `QA-EDGE-001` requires a jurisdiction map before notification, and `QA-EDGE-002` forces shelf-life reasoning onto QS 10050:2025 rather than the 2020 code of practice.

**Bahrain** has the most prescriptive rejection procedure — two branches, request letters, Askar landfill, official certificates (`BH-EDGE-001`) — and states the no-date-stickers prohibition more directly than any other GCC source (`BH-EDGE-005`).

## Deliberate known-gap rules

Qatar, Oman and Bahrain each carry a rule that forbids stating a penalty figure, because the sibling country profiles mark those amounts `NOT STATED` — Al Meezan is JavaScript-rendered, and the Omani and Bahraini penalty texts weren't retrievable. The rule tells the agent to describe the enforcement measures and escalate, rather than invent a number or transfer one by analogy from another GCC state. Saudi Arabia has a variant: penalties sit in a violations schedule that is periodically reissued, so no figure should be quoted from memory.

These are guardrails against confabulation, and they matter more than they look. A plausible-sounding fabricated fine is worse than an admitted gap.

## Integration notes

- Run `GCC-NORM-003` first: the telemetry quality gate precedes disposition logic, always.
- `expedite_sale` exists in the vocabulary only so the agent can recognise and refuse it.
- `abstain` is always available and never penalised.
- `GCC-EDGE-020` (synthetic/dropped provenance) is not overridable by operator instruction inside the artifact.
- Temperature band precedence: country technical regulation → national standard → GSO → Codex → base file.

## Caveats

Operational guardrails for agent design, not legal advice. Penalty figures, technical regulation editions and clearance workflows change across all six states — the `legal_basis` block on each rule names the instrument so you can verify at source. See `../gcc_food_law_json/CHANGELOG_AND_VERIFICATION.md` for what was verified, what was corrected, and what remains open.
