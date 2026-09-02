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
};

export function getApiDocsUrl(): string {
  return `${API_BASE}/docs`;
}
