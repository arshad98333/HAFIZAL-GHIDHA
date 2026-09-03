# Frontend Build Instructions — Sovereign-Edge Food Quality Predictor

Mobile-first PWA, "Tracking & Hacking" green terminal UI. This doc is the frontend developer's build reference — stack, project structure, design system, screen-by-screen specs, integration contracts, and edge-case handling.

---

## 1. Stack

- **Framework:** Next.js (App Router), React.
- **Styling:** Tailwind CSS.
- **State:** React Query (server state / API calls) + Zustand (local UI state — capture flow, offline queue).
- **On-device inference:** TensorFlow.js or ONNX Runtime Web, running a quantized YOLOv8n model.
- **Camera/torch:** native `getUserMedia` + `MediaStreamTrack.applyConstraints`.
- **Offline storage:** IndexedDB (via `idb` library) for the capture queue.
- **PWA:** `next-pwa` or manual service worker, installable, offline-capable for capture screens.
- **i18n/RTL:** `next-intl` or equivalent, Arabic + English, full RTL layout flip (not just text direction — mirror nav, icons, card layout).
- **Auth:** Microsoft Entra External ID via MSAL.js.
- **Realtime feed:** WebSocket or Server-Sent Events connection to the backend for the live tracking dashboard.

## 2. Project structure

```
/app
  /(auth)/login
  /(inspector)/home
  /(inspector)/capture
  /(inspector)/voice-note
  /(inspector)/review-submit
  /(inspector)/confirmation
  /(inspector)/history
  /(checker)/queue
  /(checker)/case/[id]
  /(checker)/history
  /(manager)/dashboard
  /(manager)/alerts
  /(manager)/compliance-docs
  /(admin)/devices
  /(admin)/users
  /(admin)/guardrails
  /(admin)/rag-memory
/components
  /ui            -- shared design-system primitives (buttons, cards, status dots)
  /capture        -- camera view, radar-lock overlay, torch indicator
  /queue          -- queue card, SLA timer, badge
  /feed           -- terminal-style live feed component
/lib
  /yolo           -- on-device model loading + inference
  /offline-queue  -- IndexedDB capture queue logic
  /api            -- typed API client
/styles
  tokens.css      -- color/typography design tokens
/public/models
  yolov8n.onnx (or .tfjs equivalent, quantized)
```

## 3. Design system — "Tracking & Hacking" green UX

### Color tokens
```css
--bg-primary:      #0B0F0E;   /* near-black background, never pure black */
--signal-green:    #00FF88;   /* primary accent, auto-cleared/success */
--warn-amber:      #FFB000;   /* pending / review / offline-queued */
--alert-red:       #FF3B3B;   /* high-risk / rejected / failed */
--text-muted:      #5C6B63;   /* secondary text, green-grey */
--text-primary:    #E4FFF0;   /* main text, slight green tint, not pure white */
--border-subtle:   #1C2620;
```

### Typography
- Monospace throughout: `JetBrains Mono` or `IBM Plex Mono`, fallback `ui-monospace`.
- Sizes: 14px base on mobile, 16px comfortable reading for case detail body text, never below 12px for any interactive label.

### Motion
- **Radar-lock:** a rotating sweep arc over the camera viewfinder while YOLO is scanning; snaps to a solid ring when confidence locks.
- **Scan line:** a horizontal line animation while the cloud pipeline processes (shown during upload/analysis wait states).
- **Status pulse:** amber dot pulses (opacity 0.4–1.0 loop, ~1.2s) while pending; green/red dots are steady, not animated, once resolved.
- Keep all motion under 300ms per transition except the intentional scan/radar loops — this is a utility UI, not a marketing site, don't over-animate.

### Core components to build first
1. `StatusDot` — green/amber/red, optional pulse prop.
2. `TerminalFeed` — scrolling monospace log line component, auto-scrolls, pauses on user interaction, supports a throttled "summarize" mode for high volume.
3. `CaseCard` — left-border colored by risk, tap to expand, used in queue, history, and dashboard feed.
4. `RadarCapture` — camera viewfinder wrapper with the lock animation and torch indicator overlay.
5. `SlaTimer` — countdown chip, turns red and starts pulsing past the deadline.

## 4. Screen-by-screen build spec

Each screen below lists route, purpose, required states, and the edge cases the component must render explicitly (not just handle in logic — these need visible UI states).

### `/login`
- Entra External ID login, tenant auto-detect from invite link, language toggle.
- States: default, loading, error, offline (allow cached session for capture-only access).

### `/home` (inspector)
- Large "Scan" CTA, `TerminalFeed` of last 3–5 submissions, sync indicator in top bar.
- States: empty, populated, offline (feed items show amber "queued" status).

### `/capture` (inspector)
- `RadarCapture` component: fullscreen camera, live confidence %, torch status icon.
- On mount: request camera permission, load YOLO model from `/public/models`, start inference loop (target 5–10 fps on mid-range hardware, throttle if device struggles).
- Torch trigger: attempt `applyConstraints({advanced:[{torch:true}]})` before capture; on failure/unsupported, proceed and tag frame `lighting_unstandardized: true`, show a small non-blocking flag icon — do not block capture.
- Confidence states: **scanning** (below lock threshold), **locked** (above threshold, auto-advance after ~800ms hold), **ambiguous** (confidence hovering mid-range for >2s — show manual "select item type" chip), **multi-item** (more than one bounding box detected — show "isolate one item" prompt).
- Next: auto-advance to `/voice-note` on confirmed capture.

### `/voice-note` (inspector)
- Mic button, live waveform, "skip" equally prominent as "record."
- States: idle, recording, processing (if online — attempt transcription preview), done, skipped, offline (audio queued, no preview shown, tagged for later transcription).
- Next: `/review-submit`.

### `/review-submit` (inspector)
- Thumbnail, editable detected item type, editable/removable transcript, submit button.
- Before enabling submit: run a client-side near-duplicate check (same device + item type + timestamp within 2 minutes) against local recent-submissions cache; show a warning modal if triggered, require explicit "submit anyway" confirmation.
- Next: `/confirmation`.

### `/confirmation` (inspector)
- Status chip: Sent / Queued offline / Failed (with retry).
- Auto-redirect to `/home` after ~3s, or manual "done" tap.

### `/history` (inspector)
- List of `CaseCard`s, filter by date/status, tap → read-only case detail (reuse checker's case-detail component, hide action buttons).

### `/queue` (checker)
- List of `CaseCard`s sorted by `SlaTimer` urgency, badge text sourced from `assessment.guardrail_flags` / `assessment.onDevice_cloud_agreement` / risk level — must show *why* each case is here, not just that it is.
- Empty state: explicit "Queue clear" state, not a blank screen.
- Overdue items: sort to top, red pulsing border.

### `/case/[id]` (checker)
- Sections in fixed order: photo (zoomable), transcript, AI reasoning panel, guardrail panel (visually separated card, distinct border color from the AI panel — this separation is a product requirement, not a style choice), similar-past-cases panel (RAG matches with their historical correction if any), action bar (Approve / Reject / Modify).
- Reject/Modify: opens a modal requiring free-text reason before submit is enabled.
- Locking: on mount, call a lock endpoint; if already locked by another checker, render a read-only banner "In review by [name]" and disable actions.

### `/dashboard` (manager/exec/municipal)
- `TerminalFeed` (tenant-wide), summary counters, optional site/map view.
- Feed must support pause-on-interaction and a throttled/summarized mode above a configurable event-rate threshold.

### `/alerts` (manager)
- List of alert records, delivery status, retry action on failed items — retry must be visually distinct (not buried in a menu).

### `/compliance-docs` (manager/municipal)
- Searchable/filterable PDF archive — this screen needs to be fast under load since it's used mid-audit; prioritize search responsiveness over visual flourish here.

### `/admin/devices`, `/admin/users`, `/admin/guardrails`, `/admin/rag-memory`
- Standard admin CRUD tables/forms, styled consistent with the design system but lower animation priority.
- `/admin/guardrails`: rule updates from source JSON must show a diff/review step before "activate" — never auto-apply silently.
- `/admin/rag-memory`: searchable correction log with a manual exclude/delete action per entry.

## 5. API integration contract (frontend expectations)

- `POST /api/inspections` — multipart upload (image, optional audio, onDevice metadata) → returns `inspection_id` immediately (202 Accepted), actual assessment arrives via websocket/poll.
- `GET /api/inspections/:id` — poll fallback if websocket unavailable.
- `WS /api/live-feed` — tenant-scoped stream of state-change events for `TerminalFeed` and `/dashboard`.
- `GET /api/queue` — checker's pending review items, tenant + role scoped.
- `POST /api/queue/:id/decision` — body `{ decision: approve|reject|modify, reason?, correctedFields? }`.
- `POST /api/queue/:id/lock` / `DELETE /api/queue/:id/lock` — case locking for concurrent-checker prevention.
- All endpoints require `Authorization: Bearer <Entra token>` and are tenant-scoped server-side — frontend never trusts client-side tenant filtering alone.

## 6. Offline behavior

- Capture screens (`/capture`, `/voice-note`, `/review-submit`) must fully function offline: write to IndexedDB queue instead of calling the API.
- A background sync (Service Worker `sync` event, or polling on reconnect) drains the queue in order, updating each item's local status from `queued` → `syncing` → `sent`/`failed`.
- `/home` and `/history` must render queued items distinctly (amber status) even before they've synced.
- Never let an offline capture silently vanish — every queued item must remain visible and retryable until confirmed sent.

## 7. Accessibility & i18n

- Full RTL layout for Arabic — mirror navigation, icons, and card alignment, not just text direction.
- Minimum tap target 44x44px on all interactive elements (field use, often gloved hands).
- Color is never the only status signal — pair every `StatusDot` with a text label or icon for colorblind accessibility.
- All camera/mic permission prompts need a plain-language pre-prompt explaining why access is needed before the browser's native dialog fires (improves grant rate in the field).

## 8. Performance targets

- YOLO inference: target 5+ fps on Helio G80-class hardware; degrade gracefully (reduce inference frequency, not app-breaking) on weaker devices.
- Time from capture confirm to submission: under 1s perceived (optimistic UI, actual upload can continue in background).
- Dashboard feed: must stay responsive above 50 events/minute without jank — use virtualized lists for `TerminalFeed` and `CaseCard` lists.

## 9. Build/run

```bash
npm install
npm run dev        # local dev server
npm run build       # production build
npm run start       # serve production build
```

Place the quantized YOLO model file(s) in `/public/models` before first run — inference code loads from this path and will fail silently to a "manual entry only" capture mode if the model file is missing, by design (never hard-crash the capture screen).
