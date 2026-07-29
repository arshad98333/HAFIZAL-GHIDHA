# Testing report: K2 removal, Azure Responses API reviewer, token cap removed

Generated 2026-07-28 11:01 UTC.

## What changed

1. **K2-Think removed entirely.** `scripts/k2_review.py` is deleted. No file in
   the repo calls `api.k2think.ai` or references a `K2_*` env var anymore
   (verified by grep across `cold_chain/`, `scripts/`, `tests/`, `*.md` --
   the only remaining hits are the test that asserts no `k2*` config field
   exists, and `azure_review.py`'s own docstring explaining what it replaced).
2. **New tool: `scripts/azure_review.py`.** Same job as the old K2 script
   (independent review of a sample of kept records, agree/disagree tally,
   concern flagging) but calls Azure OpenAI's **Responses API**
   (`client.responses.create`) via the exact client-construction pattern you
   supplied (`openai.OpenAI` + `azure.identity.get_bearer_token_provider`,
   scope `https://ai.azure.com/.default`, `base_url=".../openai/v1"`), not
   Chat Completions.
3. **No output token cap anywhere in the new tool**, per your instruction --
   `client.responses.create(model=deployment, input=prompt)` is called with
   no `max_output_tokens` argument at all, in both `--ping` and the review path.
4. **`scripts/generate_system_report.py` updated** to call `azure_review`
   instead of `k2_review` (import, field names, section title, `--review-limit`
   replacing `--k2-limit`).
5. **Honesty note baked into the tool itself:** this reviewer calls the
   *same* Azure deployment (`gpt-5.4-mini`, same endpoint) the pipeline
   already uses for rendering/screening/extraction and for its own agentic
   Gate A/B judging. That makes it a structurally separate second pass
   through a different API surface, not an independently-trained second
   opinion the way K2 was. Both `azure_review.py`'s module docstring and
   the generated report say this explicitly, rather than implying
   equivalence to what was removed.

## What I actually tested, and what I could not

I do not have a way to execute this from where I'm running -- two separate,
confirmed limitations, not code problems:

- **No MongoDB route.** `python scripts/smoke_test.py` from here fails Mongo
  with `Network is unreachable` at DNS resolution -- there's no network path
  to your Atlas cluster from this sandbox.
- **No Azure AD credential.** `DefaultAzureCredential` has nothing to
  authenticate with here (no `az login` session, no managed identity, no
  `AZURE_CLIENT_ID`/`AZURE_CLIENT_SECRET`/`AZURE_TENANT_ID` env vars) --
  confirmed by running `az account show` (no `az` binary at all) and
  checking the environment for Azure credential variables (none set).

So I could not pull real wave data or get a real model response. What I
verified instead:

| Check | Result |
|---|---|
| `python -m py_compile` on every changed/new file | Clean |
| `pytest` (322 tests, including 8 new for `azure_review`/`generate_system_report`) | **322 passed, 0 failed** |
| `python scripts/azure_review.py --ping` (real run, this environment) | Reached the client construction and the Responses API call correctly; failed at token acquisition with `ClientAuthenticationError`, caught cleanly by the script's own error handling (prints `FAIL <message>`, exits 1 -- no traceback, no crash) |
| `_extract_text` unit tests (mocked response objects, both the `output_text` fast path and the structural fallback) | Pass |
| `summarize_reviews` / `_drop_reasons` / `_fmt_metric_table` unit tests | Pass |
| grep for leftover `k2`/`K2` references anywhere in the repo | None except the two intentional mentions above |

The `--ping` failure above is the same class of "works on your machine, not
this sandbox" limitation you already saw with the K2 endpoint being
network-blocked here -- except this time it's an auth limitation (no AAD
credential) rather than a network one. The request itself was built
correctly and reached the point of needing a real bearer token, which only
your machine (already `az login`'d, per your first successful smoke-test
run) can provide.

## What to run yourself to get real numbers

```bash
# 1. confirm the new reviewer can authenticate and reach the deployment
python scripts/azure_review.py --ping

# 2. review a sample of a wave's kept records
python scripts/azure_review.py --wave 1 --limit 20 --out azure_review_wave01.jsonl

# 3. the full tied-together report (Gate A/B + coverage + the review above)
python scripts/generate_system_report.py --wave 1 --review-limit 20
```

Given your first `--ping` on the old K2 script worked from your machine, (1)
should work immediately -- it reuses the exact `AZURE_OPENAI_ENDPOINT` /
`AZURE_OPENAI_DEPLOYMENT` your pipeline already authenticates against.

One more thing worth doing before (2): your Mongo `cold_chain` database
still had wave-1 state from the pre-rewrite schema last time (the
`code_switched` KeyError). If you haven't already run
`scripts/reset_pipeline_state.py --yes` and regenerated a clean wave 1, do
that first -- otherwise `--wave 1` will pull whatever old-format records are
still sitting there.

Send me the output (console log and/or the `.jsonl`/`.md` files) and I'll
read through the agreement rate and any flagged disagreements with you.
