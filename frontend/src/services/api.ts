import type {
  AppSettings,
  ComparisonResult,
  DashboardSummary,
  DemoDataset,
  EventDetail,
  EventRecord,
  ExecutionRef,
  Explanation,
  GraphResponse,
  HypothesesResponse,
  ImportSummary,
  IncidentDetail,
  IncidentSummary,
  Page,
  Readiness,
  ReplayRequest,
  ReplayResponse,
  Report,
  TimelineResponse,
} from "../types/api";

/** Base URL of the API. Empty means same origin (the Vite dev server proxies /api). */
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, requestId: string | null, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((item) => params.append(key, item));
    else params.append(key, String(value));
  }
  const qs = params.toString();
  return `${API_BASE}/api/v1${path}${qs ? `?${qs}` : ""}`;
}

async function request<T>(method: string, path: string, options: { query?: Query; json?: unknown; body?: BodyInit } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let body = options.body;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), { method, headers, body });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the GhostTrace API. Is the backend running?", null);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    const error = (data as { error?: { code?: string; message?: string; request_id?: string; details?: unknown } } | null)?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `Request failed with HTTP ${response.status}.`,
      error?.request_id ?? response.headers.get("X-Request-ID"),
      error?.details,
    );
  }
  return data as T;
}

export interface UploadOptions {
  name?: string;
  format?: "auto" | "jsonl" | "json" | "csv";
  fieldMapping?: Record<string, string> | null;
}

export const api = {
  health: () => request<{ status: string; version: string }>("GET", "/health"),
  ready: () => request<Readiness>("GET", "/ready"),
  settings: () => request<AppSettings>("GET", "/settings"),
  dashboard: () => request<DashboardSummary>("GET", "/dashboard/summary"),

  listImports: (query: { limit?: number; offset?: number; status?: string } = {}) =>
    request<Page<ImportSummary>>("GET", "/imports", { query }),
  getImport: (id: string) => request<ImportSummary>("GET", `/imports/${encodeURIComponent(id)}`),
  deleteImport: (id: string) => request<undefined>("DELETE", `/imports/${encodeURIComponent(id)}`),
  uploadImport: (file: File, options: UploadOptions = {}) => {
    const form = new FormData();
    form.append("file", file);
    if (options.name) form.append("name", options.name);
    form.append("format", options.format ?? "auto");
    if (options.fieldMapping && Object.keys(options.fieldMapping).length > 0) {
      form.append("field_mapping", JSON.stringify(options.fieldMapping));
    }
    return request<ImportSummary>("POST", "/imports", { body: form });
  },
  listDemoDatasets: () => request<DemoDataset[]>("GET", "/datasets/demo"),
  importDemo: (name: string) => request<ImportSummary>("POST", `/datasets/demo/${encodeURIComponent(name)}/import`),
  importEvents: (id: string, query: Query) => request<Page<EventRecord>>("GET", `/imports/${encodeURIComponent(id)}/events`, { query }),
  importGraph: (id: string) => request<GraphResponse>("GET", `/imports/${encodeURIComponent(id)}/graph`),

  listIncidents: (query: { import_id?: string; severity?: string; evidence_status?: string; limit?: number; offset?: number } = {}) =>
    request<Page<IncidentSummary>>("GET", "/incidents", { query }),
  getIncident: (id: string) => request<IncidentDetail>("GET", `/incidents/${encodeURIComponent(id)}`),
  getHypotheses: (id: string) => request<HypothesesResponse>("GET", `/incidents/${encodeURIComponent(id)}/hypotheses`),
  getTimeline: (id: string, query: Query) => request<TimelineResponse>("GET", `/incidents/${encodeURIComponent(id)}/timeline`, { query }),
  getIncidentGraph: (id: string) => request<GraphResponse>("GET", `/incidents/${encodeURIComponent(id)}/graph`),
  getIncidentEvent: (id: string, eventId: string) =>
    request<EventDetail>("GET", `/incidents/${encodeURIComponent(id)}/events/${encodeURIComponent(eventId)}`),
  createReplay: (id: string, body: ReplayRequest) => request<ReplayResponse>("POST", `/incidents/${encodeURIComponent(id)}/replay`, { json: body }),
  createExplanation: (id: string) => request<Explanation>("POST", `/incidents/${encodeURIComponent(id)}/explanations`),

  createComparison: (baseline: ExecutionRef, target: ExecutionRef) =>
    request<ComparisonResult>("POST", "/comparisons", { json: { baseline, target } }),
  listComparisons: () => request<Page<ComparisonResult>>("GET", "/comparisons", { query: { limit: 20 } }),

  createReport: (incidentId: string, format: "markdown" | "json", comparisonId?: string | null) =>
    request<Report>("POST", `/incidents/${encodeURIComponent(incidentId)}/reports`, {
      json: { format, comparison_id: comparisonId || null },
    }),
  listReports: (incidentId: string) => request<Report[]>("GET", `/incidents/${encodeURIComponent(incidentId)}/reports`),
  reportDownloadUrl: (report: Report) => `${API_BASE}${report.download_url}`,
};
