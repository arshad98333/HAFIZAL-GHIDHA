# GCC Food Law JSON — Verification & Change Log

**Compiled:** 28 July 2026 · **Schema version:** 1.0.0 · **Files:** 6 country JSONs + schema

| # | File | Country | Source PDF supplied | What the PDF actually is | Confidence |
|---|------|---------|---------------------|--------------------------|------------|
| 01 | `01_uae_food_law.json` | UAE | `Federal Law No. (10) _UAE.pdf` | The primary statute itself (22 articles) | High |
| 02 | `02_saudi_arabia_food_law.json` | Saudi Arabia | `SFDA_KSA.pdf` | SFDA import conditions guide (8 articles + certificate models) | High |
| 03 | `03_qatar_food_law.json` | Qatar | `1662838504863_QATAR.pdf` | MOPH food service code of practice, Rev. 0, Oct 2020 | High |
| 04 | `04_kuwait_food_law.json` | Kuwait | `kuw221743E_KUWAIT.pdf` | Ministerial Resolution 6/2023 + Imported Food Regulations (64 articles) | High |
| 05 | `05_oman_food_law.json` | Oman | `D1.Session.1.6_OMAN.pdf` | A conference presentation — **no legal content** | High (rebuilt from official sources) |
| 06 | `06_bahrain_food_law.json` | Bahrain | `638242460024477544_BAHRAIN.pdf` | MOH food premises guideline FCS/3 v4 | Medium-high |

Only two of the six PDFs were actual legal instruments. Four were guidance or presentation material, so the legal framework in those files was reconstructed from official gazettes, legal portals and competent-authority sources.

---

## Corrections made — things in your PDFs that are wrong or superseded

### Oman — the most serious one
The presentation shows the **Food Safety and Quality Centre under the Ministry of Regional Municipalities and Water Resources**. That is outdated. **Royal Decree 92/2020** transferred the Centre to the **Ministry of Agriculture, Fisheries Wealth and Water Resources (MAFWR)**, which is now the national competent authority for food safety. Oman also moved from a fragmented multi-agency model to an integrated food control system by the same decree. The presentation's GFSI/food-safety scores stop at 2022 and its National Food Security Strategy is described as "under major revision" — don't quote either as current.

### UAE
Federal Law 10/2015 is still in force, but its preamble cites five instruments that have since been replaced:

| Cited in the 2015 preamble | Now |
|---|---|
| Federal Law 24/2006 Consumer Protection | Federal Law 15/2020 (+ Cabinet Decision 66/2023) |
| Federal Law 3/1987 Penal Code | Federal Decree-Law 31/2021 |
| Federal Law 35/1992 Criminal Procedure | Federal Decree-Law 38/2022 |
| Federal Law 37/1992 Trademarks | Federal Decree-Law 36/2021 |
| Federal Law 8/1984 Commercial Companies | Federal Decree-Law 32/2021 |

Also: **ESMA** (Federal Law 28/2001) was abolished in 2020 — read every "ESMA" reference as **MOIAT**. The proposing ministry, "Ministry of Environment and Water", is now **MOCCAE**. And the official English PDF prints the Hijri date as *21 Muharram 1427 AH*, which does not correspond to 3 November 2015 — the correct equivalent is *1437 AH*. That's a typo in the published translation.

### Saudi Arabia
Your import guide is undated and reflects an earlier edition. Two structural changes since:
- A **new SFDA Law was enacted in 2025**, superseding the 2007 SFDA Act (Royal Decree M/6 of 1428 AH). SFDA now has legal personality with financial and administrative independence and reports to the President of the Council of Ministers.
- The underlying statute for food is the **Food Law, Royal Decree M/1 (1436 AH / 2014)** — 45 articles in 12 chapters. Article 7 is the legal basis for your import-conditions document.

Not reflected in the PDF: mandatory **menu labelling from 1 July 2025** (calories, saltshaker high-sodium symbol, caffeine disclosure, burn-off time) and the **2025 updated schedule of food law violations** issued by MOMAH with SFDA.

### Qatar
Law 8/1990 is still the primary law, as amended by **Law 4/2014**. The big addition since your code of practice: **Ministerial Decision 102/2025** adopting **Qatari Technical Regulation QS 10050:2025 on the shelf life of food products** (December 2025). Also, "Supreme Council of Health" is now the **Ministry of Public Health**, and "Ministry of Municipality and Urban Planning" is now the **Ministry of Municipality**. Several GSO editions cited in the code are old (GSO 21/1984, 323/1994, 969/1997, 1694/2005, 1909/2009, 1971/2009, 2309/2013).

### Kuwait
Nothing outdated — your PDF *is* the current instrument, and it is itself the repealer (Article 2 cancels the 2017 Imported Food Regulations, effective 1 September 2023). Context added: enabling law **112/2013 as amended by Law 16/2019** (stiffer penalties; port laboratories under Art. 12), plus **Ministerial Decree 351/2025** on energy drinks, which post-dates the PDF.

### Bahrain
Your guideline cites no legislation by number. The operative basis is **Public Health Law No. 34 of 2018**. Two instruments post-date the guideline: **Ministerial Resolution 89/2022** (prohibits children's gelatin candy containing konjac / E425) and **Resolution 115/2024** (veterinary preparations in poultry and food-producing animals). For import rules, the **2024 Food Importers Guide** supersedes the import content here.

One correction worth flagging: **there is no "Bahrain National Food Safety Authority."** Web searches surface that name, but it belongs to another country's body. The competent authority is the **Food Control Section, Public Health Directorate, Ministry of Health**.

---

## Region-wide update

**GSO 2055-1:2026** — draft revision of *Halal Food, Part 1: General Requirements* was released for public consultation on **17 February 2026**, comments due **18 April 2026**. It tightens supply-chain, certification and labelling rules. **GSO 2055-1:2015 remains the operative version** until formally adopted; all six files record it that way.

---

## Deliberate gaps — where I would not guess

Each of these is marked `"NOT STATED"` or carries a confidence flag inside the JSON rather than being filled with a plausible-looking number.

| Country | Gap | Why |
|---|---|---|
| Qatar | Fine/imprisonment amounts, Law 8/1990 Arts. 19–23 as amended | Al Meezan is JavaScript-rendered; no machine-readable official text available |
| Oman | Fine bands under RD 84/2008 and MD 2/2010 | No accessible official text |
| Oman | Decision number of the 2025 Article 30 bis amendment | Reported without a number; substance verified, number not |
| Oman | Plant Quarantine Law citation | The FSQC-affiliated 2025 review cites both "RD 91/2000 amended to 47/2007" and "RD 47/2004". Both recorded, flagged |
| Bahrain | Penalty amounts under Law 34/2018 | Guideline refers only to "the penalties under the act of Public Health Law" |
| Bahrain | Status of Legislative Decree 3/1985 | May be superseded in whole or part by Law 34/2018 — needs a lawyer's read |
| Saudi Arabia | Royal decree number/date of the 2025 SFDA Law | Substance well documented across sources; the decree number was not independently confirmed |
| UAE | Whether the announced 2025 legislative package has been gazetted | Announced by MOCCAE; issuance unconfirmed at compile date. Recorded under `pending_legislation` |

---

## Verification method

1. Text extracted from all six PDFs with `pdftotext -layout`.
2. Every authority name, law number, article reference and requirement cross-checked against: official legal portals (uaelegislation.gov.ae, almeezan.qa, laws.boe.gov.sa, mjla.gov.om, decree.om, moh.gov.bh), FAOLEX/ECOLEX/InforMEA, competent-authority websites, and current regulatory reporting.
3. Where a PDF's claim conflicted with a current official source, the official source won and the conflict was logged in `outdated_items_found_in_supplied_pdf`.
4. All six files validated against `00_schema.json` (JSON Schema 2020-12) — **0 errors**.

---

## Before you rely on this

Fine amounts, technical regulation editions and registration workflows change frequently across all six states. Every file carries `official_sources` with direct links — check the specific instrument at source before using any of this for a filing, a submission or a compliance decision. This is a research compilation, not legal advice.
