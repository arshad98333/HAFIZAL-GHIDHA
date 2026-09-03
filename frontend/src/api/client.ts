const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

export type Health = { status: string; environment?: string; error?: string };
export type Ready = { status: string; mongodb_db?: string; error?: string };
export type Job = {
  job_id: string;
  name: string;
  status: string;
  wave?: number;
  result?: Record<string, unknown>;
  error?: string;
};
export type WaveAudit = {
  wave: number;
  generation_log_rows: number;
  kept_records: number;
  gate_a_passed: boolean | null;
  gate_a_metrics?: Record<string, number>;
  gate_a_failures?: string[];
};

export type SimulateResult = {
  product: string;
  fault_mode: string;
  jurisdiction: string;
  artifact_type: string;
  seed: number;
  readings_c: number[];
  interval_min: number;
  ambient_c: number | null;
  days_since_production: number | null;
  sensor_fault: boolean;
  peak_season: boolean;
  missing_fields: string[];
  temp_band_min_c: number | null;
  temp_band_max_c: number;
  disposition: string;
  rule_id: string;
  excursion_minutes: number;
  peak_temp_c: number | null;
  remaining_shelf_days: number | null;
  render_prompt: string;
  artifact_preview: string;
  guardrail_violations: string[];
  steps: { id: string; title: string; detail: string; status: string }[];
  spec_regime: string;
  spec_clause: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  baseUrl: API_BASE,
  health: () => request<Health>("/health"),
  ready: () => request<Ready>("/ready"),
  meta: () => request<{ service: string; docs: string }>("/"),
  audit: (wave: number) => request<WaveAudit>(`/waves/${wave}/audit`),
  gateA: (wave: number) => request<Record<string, unknown>>(`/waves/${wave}/gate-a`),
  kpi: (wave: number) => request<Record<string, unknown>>(`/waves/${wave}/kpi`),
  recordsCount: (wave: number) =>
    request<{ total: number; kept: number; by_outcome: Record<string, number> }>(
      `/waves/${wave}/records/count`,
    ),
  records: (wave: number, limit = 20, offset = 0) =>
    request<{ total: number; records: Record<string, unknown>[] }>(
      `/waves/${wave}/records?limit=${limit}&offset=${offset}`,
    ),
  jobs: (wave?: number) =>
    request<Job[]>(`/jobs${wave ? `?wave=${wave}` : ""}`),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  coverage: () => request<Record<string, unknown>>("/coverage"),
  ledger: () => request<Record<string, unknown>[]>("/ledger"),
  post: (path: string, body?: unknown) =>
    request<Job>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  simulate: (body: {
    product: string;
    fault_mode: string;
    jurisdiction: string;
    artifact_type: string;
    seed: number;
    is_adversarial?: boolean;
    is_abstention?: boolean;
  }) => request<SimulateResult>("/simulate", { method: "POST", body: JSON.stringify(body) }),
};

// -- compliance Q&A chat (SSE) ---------------------------------------------- //

export type AskContextEvent = {
  jurisdiction: string | null;
  product: string | null;
  requested_product: string | null;
  product_mismatch: boolean;
  matched_rule_ids: string[];
  has_citation: boolean;
};

export type AskStepEvent = { id: string; title?: string; delta?: string; output?: string; error?: string };

export type AskFinalEvent = { status: string; answer: string; error: string | null };

export type AskRateLimitedEvent = { id: string; attempt: number; wait_s: number; reason: string };

export type AskEvalEvent = {
  cited_rule_ids: string[];
  verified_rule_ids: string[];
  unverified_rule_ids: string[];
  cited_gso_codes: string[];
  verified_gso_codes: string[];
  unverified_gso_codes: string[];
  all_verified: boolean;
};

export type AskEventHandlers = {
  onContext?: (data: AskContextEvent) => void;
  onStepStart?: (data: AskStepEvent) => void;
  onStepDelta?: (data: AskStepEvent) => void;
  onStepDone?: (data: AskStepEvent) => void;
  onStepError?: (data: AskStepEvent) => void;
  onRateLimited?: (data: AskRateLimitedEvent) => void;
  onEval?: (data: AskEvalEvent) => void;
  onFinal?: (data: AskFinalEvent) => void;
  onDone?: () => void;
};

/**
 * POSTs to an SSE endpoint and hand-parses the text/event-stream response,
 * dispatching each frame to `onEvent`. EventSource can't be used here
 * (GET-only, no request body/headers) — this reads the fetch body's
 * ReadableStream directly and splits on the SSE frame boundary ("\n\n"),
 * the same wire format every SSE route in this backend emits
 * (cold_chain/api/routes/compliance.py, .../liveops.py). Shared by both the
 * Ask chat and LiveOps narration rather than duplicated per feature.
 */
async function streamSse(
  path: string,
  body: unknown,
  onEvent: (eventName: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (eventName: string, dataText: string) => {
    let data: unknown = null;
    try {
      data = dataText ? JSON.parse(dataText) : null;
    } catch {
      return;
    }
    onEvent(eventName, data);
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let eventName = "message";
      let dataText = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataText += line.slice(5).trim();
      }
      dispatch(eventName, dataText);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function dispatchAskEvent(handlers: AskEventHandlers, eventName: string, data: unknown): void {
  switch (eventName) {
    case "context":
      handlers.onContext?.(data as AskContextEvent);
      break;
    case "step_start":
      handlers.onStepStart?.(data as AskStepEvent);
      break;
    case "step_delta":
      handlers.onStepDelta?.(data as AskStepEvent);
      break;
    case "step_done":
      handlers.onStepDone?.(data as AskStepEvent);
      break;
    case "step_error":
      handlers.onStepError?.(data as AskStepEvent);
      break;
    case "rate_limited":
      handlers.onRateLimited?.(data as AskRateLimitedEvent);
      break;
    case "eval":
      handlers.onEval?.(data as AskEvalEvent);
      break;
    case "final":
      handlers.onFinal?.(data as AskFinalEvent);
      break;
    case "done":
      handlers.onDone?.();
      break;
    default:
      break;
  }
}

/**
 * POSTs to /compliance/ask and streams the 4-step reasoning chain.
 */
export async function askComplianceStream(
  body: { question: string; jurisdiction?: string | null; product?: string | null },
  handlers: AskEventHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await streamSse("/compliance/ask", body, (eventName, data) => dispatchAskEvent(handlers, eventName, data), signal);
}

// -- LiveOps (random truck scenario + grounded narration) ------------------ //

export type LiveOpsScenario = {
  scenario_id: string;
  source: string;
  truck_id: string;
  product: string;
  jurisdiction: string;
  fault_mode: string;
  artifact_type: string;
  seed: number;
  readings_c: number[];
  interval_min: number;
  ambient_c: number | null;
  days_since_production: number | null;
  sensor_fault: boolean;
  peak_season: boolean;
  disposition: string;
  rule_id: string;
  excursion_minutes: number;
  peak_temp_c: number | null;
  remaining_shelf_days: number | null;
  temp_band_min_c: number | null;
  temp_band_max_c: number;
  spec_regime: string;
  spec_clause: string;
  narrative_opening: string;
  generated_at: number;
};

export type LiveOpsContextEvent = {
  scenario_id: string;
  jurisdiction: string | null;
  product: string | null;
  matched_rule_ids: string[];
  has_citation: boolean;
};

export type LiveOpsEventHandlers = {
  onContext?: (data: LiveOpsContextEvent) => void;
  onStepStart?: (data: AskStepEvent) => void;
  onStepDelta?: (data: AskStepEvent) => void;
  onStepDone?: (data: AskStepEvent) => void;
  onStepError?: (data: AskStepEvent) => void;
  onRateLimited?: (data: AskRateLimitedEvent) => void;
  onEval?: (data: AskEvalEvent) => void;
  onFinal?: (data: AskFinalEvent) => void;
  onDone?: () => void;
};

export async function fetchLiveOpsScenario(signal?: AbortSignal): Promise<LiveOpsScenario> {
  return request<LiveOpsScenario>("/liveops/scenario", { method: "POST", signal });
}

/**
 * POSTs the scenario (round-tripped from fetchLiveOpsScenario) plus an
 * optional officer note to /liveops/narrate and streams the 3-step
 * narration (What Happened / The Problem / GSO-Aligned Solution).
 */
export async function liveOpsNarrateStream(
  scenario: LiveOpsScenario,
  officerNote: string | null,
  handlers: LiveOpsEventHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const body = { ...scenario, officer_note: officerNote || null };
  await streamSse(
    "/liveops/narrate",
    body,
    (eventName, data) => {
      switch (eventName) {
        case "context":
          handlers.onContext?.(data as LiveOpsContextEvent);
          break;
        case "step_start":
          handlers.onStepStart?.(data as AskStepEvent);
          break;
        case "step_delta":
          handlers.onStepDelta?.(data as AskStepEvent);
          break;
        case "step_done":
          handlers.onStepDone?.(data as AskStepEvent);
          break;
        case "step_error":
          handlers.onStepError?.(data as AskStepEvent);
          break;
        case "rate_limited":
          handlers.onRateLimited?.(data as AskRateLimitedEvent);
          break;
        case "eval":
          handlers.onEval?.(data as AskEvalEvent);
          break;
        case "final":
          handlers.onFinal?.(data as AskFinalEvent);
          break;
        case "done":
          handlers.onDone?.();
          break;
        default:
          break;
      }
    },
    signal,
  );
}

// -- branded PDF export ------------------------------------------------------ //

export type DecisionTraceExport = {
  kind: "ask" | "liveops";
  title: string;
  jurisdiction?: string | null;
  product?: string | null;
  meta_lines: string[];
  steps: { id: string; title: string; output: string }[];
  final_answer: string;
  citation_eval: AskEvalEvent | null;
};

/**
 * Triggers a browser download of `blob` as `filename`. Shared by every page
 * that offers a PDF export button so the download mechanics (object URL
 * creation/cleanup, temporary <a> click) live in exactly one place.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * Fetches the branded decision-trace PDF and returns it as a Blob for the
 * caller to trigger a download from (see `downloadBlob`).
 */
export async function exportDecisionTracePdf(payload: DecisionTraceExport): Promise<Blob> {
  const res = await fetch(`${API_BASE}/export/decision-trace.pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.blob();
}

const API_DIRECT = (import.meta.env.VITE_API_DIRECT_URL || "").replace(/\/$/, "");

export function getApiDocsUrl(): string {
  if (API_DIRECT) return `${API_DIRECT}/docs`;
  if (API_BASE.startsWith("http")) return `${API_BASE}/docs`;
  return "http://127.0.0.1:8080/docs";
}
