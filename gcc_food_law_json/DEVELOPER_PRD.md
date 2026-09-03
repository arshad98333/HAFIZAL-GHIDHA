# Sovereign-Edge Food Quality Predictor — Developer PRD

Web app that predicts remaining shelf life / spoilage risk of perishable food (eggs, fish, mutton, chicken) from a phone camera, combining an on-device YOLO mobile model with a cloud AI model for accuracy, gated by human review before anything ships as an alert.

---

## 1. What the project does

A user opens a web app on any camera-equipped device (phone, laptop — no install required). They point the camera at a food item (e.g., an egg). The app automatically fires the torch to standardize lighting, captures a frame once a lightweight on-device YOLO model locks a confident detection, and sends that frame (plus an optional voice note) to the cloud. The cloud pipeline runs a heavier AI model to refine the on-device read, cross-checks the result against real food-safety law for the relevant country, and returns a shelf-life / spoilage-risk prediction as a range with a confidence level — never a fake exact hour figure. High-risk or legally-flagged predictions are routed to a human reviewer (maker-checker) before any alert goes out. Every human correction is stored and fed back into future predictions (RAG memory), so accuracy improves over time instead of repeating the same mistakes.

## 2. How it does it — end to end

1. **Capture (client, in-browser).** User points the camera at the item. A YOLO mobile model (YOLOv8n via TensorFlow.js, or ONNX Runtime Web as an alternative runtime) runs directly in the browser, detects the item, and tracks a confidence score frame by frame.
2. **Lighting standardization.** Once the model is close to a confident lock, the app triggers the device torch via `navigator.mediaDevices.getUserMedia` + `track.applyConstraints({advanced:[{torch:true}]})`, waits a beat for exposure to settle, then captures the frame. If torch control fails (common on some Android/Chrome builds), capture proceeds anyway and the frame is tagged `lighting_unstandardized: true`.
3. **On-device pre-prediction.** The YOLO mobile model doesn't just detect the item — it also extracts a rough feature set (bounding box, class, visual confidence, any coarse quality signal the model is trained for, e.g., shell discoloration on an egg) and produces a first-pass, low-confidence shelf-life estimate. This travels with the frame as a prior, not a final answer.
4. **Upload.** Frame + on-device features + optional voice note + device/tenant metadata are sent to the backend (direct HTTPS API call from the PWA in the common path; MQTT via IoT Hub for dedicated field devices operating in low-connectivity sites).
5. **Cloud refinement (the "AI model" pass).** A cloud vision-language model (Azure AI Foundry deployment) re-analyzes the full-resolution frame, taking the on-device YOLO output as context rather than starting blind. This catches what a small mobile model misses — subtle discoloration, texture, packaging condition — and produces a structured spoilage-indicator readout.
6. **Voice fusion (if provided).** Voice note is transcribed (Deepgram Nova-3, Gulf Arabic dialect support) and merged into the same evidence object as the vision output.
7. **Memory retrieval (RAG).** The current case's evidence is embedded and matched against a vector index of past cases and their human corrections. Similar past cases — and what they were corrected to — are injected as grounding context before the final prediction is made.
8. **Final prediction.** A reasoning step combines on-device YOLO output, cloud vision output, voice evidence, and RAG context into a shelf-life/spoilage-risk range with a confidence score and a plain-language reasoning summary.
9. **Guardrail check.** The prediction is checked against the country-specific food-law dataset (microbiological limits, storage/transport rules) independent of the AI's own confidence — a legal rule can override a "looks fine" AI read.
10. **Maker-checker gate.** If risk is high, a guardrail fired, on-device and cloud predictions disagree significantly, or the case is a random QA sample, it goes to a human review queue instead of auto-dispatching. Otherwise it proceeds automatically.
11. **Persist, document, alert.** Final result is written to the database, a compliance PDF is generated, and WhatsApp/email alerts go out to the relevant people.
12. **Feedback loop.** Any human correction from step 10 is written back into the RAG memory store, improving future predictions on similar cases.

## 3. Why two models instead of one

The on-device YOLO mobile model is fast and works offline, but it's small and constrained by phone hardware (no GPU acceleration in-browser on most Android devices) — good enough for detection and a rough first-pass estimate, not accurate enough alone for a result you'd put in a compliance report. The cloud AI model is slower and requires connectivity, but has far more capacity and can be grounded with retrieved past cases (RAG). Combining them gives a fast, always-available first read plus an accurate, auditable final read — and the disagreement between the two is itself a useful signal that triggers human review.

## 4. Tech stack

### Client / Web App
- **Framework:** Next.js (React), PWA-enabled, installable, works offline for capture.
- **Styling:** Tailwind CSS, mobile-first, RTL support for Arabic.
- **On-device inference:** TensorFlow.js or ONNX Runtime Web running a YOLOv8n (or similar lightweight YOLO variant) model, quantized for mobile.
- **Camera/torch control:** MediaStreamTrack API (`getUserMedia`, `applyConstraints`).
- **Offline queueing:** IndexedDB-backed capture queue, syncs when connectivity returns.

### Ingestion
- **Azure IoT Hub** (UAE Central) — for dedicated field devices publishing over MQTT; device identity per phone.
- **Azure Data Lake Storage Gen2** (UAE Central) — raw image/audio/JSON landing zone.
- **Azure API Management** — public HTTPS gateway for the web app's direct upload path, auth validation, per-tenant rate limiting.
- **Azure Event Grid** — triggers the backend pipeline on new blob/message arrival.

### Orchestration / Backend
- **LangGraph** (Python) — the pipeline backbone; every step in Section 2 (steps 5–12) is a graph node with shared state and checkpointing, so the maker-checker gate can pause and resume a run.
- **Azure Functions** — hosts the LangGraph graph; HTTP-triggered from the web app, Event Grid-triggered from IoT Hub/Data Lake.

### AI / ML
- **On-device:** YOLOv8n (or equivalent), TF.js/ONNX Runtime Web.
- **Cloud vision-language model:** Azure AI Foundry deployment. Confirm in-region (UAE) inference availability before committing; if using a model like GPT-4o whose inference isn't hosted in-region yet, document the cross-border routing explicitly as a PDPL Article 22 safeguards exception.
- **Speech-to-text:** Deepgram Nova-3 (Gulf/Khaleeji Arabic dialect support).
- **Embeddings:** Azure AI Foundry multilingual embedding deployment, for the RAG memory layer (must handle Arabic transcripts).

### Data
- **MongoDB on Azure, UAE Central** — either Cosmos DB for MongoDB (vCore) if confirmed available in-region, or self-managed MongoDB on Azure VMs if not yet available there.
- **Vector index:** Azure AI Search (Arabic-aware analyzers) or Cosmos DB for MongoDB vCore's native vector search — same database as operational data where possible, to avoid running two systems.

### Auth / Multi-tenancy
- **Microsoft Entra External ID** — multi-tenant login, role-based access (maker / checker / manager / municipal-viewer / admin).
- `tenant_id` scoping enforced on every query — no cross-tenant reads.

### Alerting
- **Azure Communication Services** — WhatsApp Business channel (pre-approved templates) and email with PDF attachment.

### Observability
- **Azure Monitor / Application Insights** — per-node latency and failure tracking, feeds the live tracking dashboard, SLA-breach alerting on the review queue.

## 5. Core data model (MongoDB)

```
devices           { device_id, tenant_id, site_id, last_seen, torch_capable }
inspections       { inspection_id, tenant_id, device_id, food_type,
                     onDevice_confidence, onDevice_estimate,
                     snapshot_uri, audio_uri, voice_transcript, created_at }
assessments       { inspection_id (ref), spoilage_risk_low_hr, spoilage_risk_high_hr,
                     risk_level, confidence, model_version, foundry_region_used,
                     reasoning_summary, guardrail_flags, onDevice_cloud_agreement }
review_queue      { case_id, maker_id, checker_id, status, reason,
                     sla_deadline, decided_at }
alerts            { assessment_id (ref), channel, recipient, status,
                     sent_at, retry_count }
compliance_documents { assessment_id (ref), pdf_uri, generated_at, recipients }
lessons_learned   { case_id, arabic_transcript, evidence_summary, ai_output,
                     checker_correction, correction_reason, food_type, country,
                     embedding_ref, created_at }
audit_log         { actor, action, entity_ref, timestamp }   // append-only
guardrail_rules   { country, rule_source, version, rules[] } // from GCC food-law JSON
```

## 6. LangGraph node reference

| Node | Input | Output | Notes |
|---|---|---|---|
| `ingest` | raw payload from Data Lake/API | validated evidence object | rejects malformed/incomplete payloads |
| `transcribe` | audio_uri | voice_transcript | skipped cleanly if no audio provided |
| `vision_analysis` | snapshot_uri, onDevice_estimate | structured cloud vision readout | takes on-device output as prior context |
| `fusion` | vision + transcript + onDevice data | merged evidence object | flags disagreement between on-device and cloud reads |
| `rag_retrieval` | merged evidence object | top-k similar past cases + corrections | embeds Arabic transcript + evidence summary |
| `spoilage_reasoning` | fused evidence + RAG context | risk range, risk level, confidence, reasoning_summary | never outputs a single exact hour |
| `compliance_guardrails` | assessment + tenant country | guardrail_flags | independent of AI confidence; can override |
| `maker_checker_gate` | assessment + guardrail_flags | routed (auto-clear) or paused (review) | LangGraph `interrupt_before`, checkpointed |
| `persist` | final assessment | Mongo writes | inspections, assessments, audit_log |
| `generate_compliance_doc` | assessment | PDF | for municipal/exec distribution |
| `dispatch_alerts` | assessment + PDF | alert records | WhatsApp + email via Communication Services |
| `feedback_capture` | checker correction (if any) | lessons_learned write | closes the RAG improvement loop |

## 7. Edge cases the build must handle (priority — see product PRD for full list)

- Torch trigger fails silently on some Android/Chrome builds → capture proceeds, frame tagged `lighting_unstandardized`.
- On-device confidence sits in a grey zone → manual "confirm item type" fallback, not a forced bad detection.
- Weak/no connectivity → offline capture queue, syncs on reconnect, visible queued state.
- On-device and cloud predictions disagree meaningfully → forces `maker_checker_gate` review, regardless of either confidence score alone.
- Guardrail fires but AI confidence is low-risk → guardrail wins, routed to review, shown as a distinct reason from AI-driven review.
- Duplicate/near-duplicate captures → dedup check before submission.
- Checker unavailable/queue overdue → SLA timer + escalation, not silent aging.
- Alert delivery failure (WhatsApp/email bounce) → visible status + retry, not fire-and-forget.

## 8. Build order

1. **Foundations** — Azure resource group (UAE Central), IoT Hub, Data Lake, MongoDB instance, Communication Services channels. Prove raw data flows end to end with no AI yet.
2. **Edge capture** — YOLO mobile model in-browser, torch trigger, capture + offline queue.
3. **LangGraph skeleton** — graph wired with mocked model calls, deployed as an Azure Function, writes to MongoDB.
4. **Real model integration** — wire in the cloud vision model and Deepgram; validate on-device vs. cloud fusion logic.
5. **Maker-checker** — review queue, SLA timers, approve/reject/modify UI.
6. **Alerting** — WhatsApp + email + PDF generation.
7. **RAG memory** — build once there's real correction data to populate it; wire `rag_retrieval` and `feedback_capture`.
8. **Guardrails** — wire `compliance_guardrails` to the real GCC food-law JSON dataset, reviewable before going live.
9. **Compliance hardening** — PDPL data-flow documentation, cross-border exception sign-off if applicable, encryption/retention policy.
10. **Pilot** — deploy to one real site, measure false-positive/negative rate against manual inspection.

## 9. Environment / setup notes for developers

- Azure region for all resources: **UAE Central (Abu Dhabi)** — not UAE North (Dubai). Keep this consistent across every config file and IaC template.
- Confirm Cosmos DB for MongoDB (vCore) region availability before writing data-access code; have the self-managed MongoDB-on-VM fallback ready.
- Confirm Azure AI Foundry model region support before wiring `vision_analysis`; document any cross-border routing decision in `assessments.foundry_region_used`.
- Store all secrets (Deepgram key, Azure connection strings, Communication Services credentials) in Azure Key Vault, referenced by Functions via managed identity — not in `.env` files committed to the repo.
- LangGraph checkpointer should be backed by the same MongoDB instance so paused (`maker_checker_gate`) runs survive Function cold starts.
