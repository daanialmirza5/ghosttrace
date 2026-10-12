// Types mirroring the backend's Pydantic response schemas (backend/app/schemas).

export type Severity = "debug" | "info" | "warning" | "error" | "critical";
export type EventType =
  | "log"
  | "request"
  | "span"
  | "dependency_call"
  | "exception"
  | "timeout"
  | "retry"
  | "deployment"
  | "config_change"
  | "metric"
  | "healthcheck";
export type IncidentSeverity = "critical" | "major" | "minor";
export type EvidenceStatus = "sufficient" | "ambiguous" | "insufficient";
export type Uncertainty = "low" | "medium" | "high";
export type NodeStatus = "healthy" | "degraded" | "failing" | "unknown";
export type TimelineCategory =
  | "error"
  | "warning"
  | "request"
  | "change"
  | "retry"
  | "timeout"
  | "dependency_failure"
  | "log";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface EventRecord {
  event_id: string;
  timestamp: string;
  service: string;
  environment: string;
  severity: Severity;
  event_type: EventType;
  message: string;
  trace_id: string | null;
  span_id: string | null;
  parent_span_id: string | null;
  request_id: string | null;
  deployment_version: string | null;
  duration_ms: number | null;
  status_code: number | null;
  target_service: string | null;
  error_type: string | null;
  attributes: Record<string, string | number | boolean | null>;
  event_id_derived: boolean;
}

export interface RecordError {
  position: number;
  kind: "line" | "record" | "row";
  message: string;
  field: string | null;
}

export interface ImportSummary {
  id: string;
  name: string;
  source_filename: string | null;
  demo_dataset: string | null;
  format: string | null;
  status: "completed" | "completed_with_errors" | "failed";
  created_at: string;
  completed_at: string | null;
  size_bytes: number;
  content_sha256: string;
  total_records: number;
  accepted: number;
  rejected: number;
  duplicates: number;
  warnings: Record<string, number>;
  errors: RecordError[];
  errors_truncated: boolean;
  file_error: string | null;
  first_event_at: string | null;
  last_event_at: string | null;
  services: string[];
  analysis_status: "pending" | "completed" | "failed" | "skipped";
  analysis_error: string | null;
  analysis_ms: number | null;
  incident_count: number;
}

export interface DemoDataset {
  name: string;
  title: string;
  summary: string;
  filename: string;
  format: "jsonl" | "json" | "csv";
  size_bytes: number;
  field_mapping: Record<string, string> | null;
}

export interface Signal {
  id: string;
  type: string;
  basis: "observed" | "inferred";
  service: string;
  target_service: string | null;
  start: string;
  end: string;
  count: number;
  description: string;
  evidence_event_ids: string[];
  metrics: Record<string, string | number>;
}

export interface SignalContribution {
  name: string;
  weight: number;
  value: number;
  contribution: number;
  explanation: string;
  evidence_event_ids: string[];
}

export interface Contradiction {
  name: string;
  penalty: number;
  explanation: string;
  evidence_event_ids: string[];
}

export interface Hypothesis {
  rank: number;
  service: string;
  candidate_kind: "observed" | "inferred";
  statement: string;
  score: number;
  score_label: string;
  uncertainty: Uncertainty;
  signals: SignalContribution[];
  contradictions: Contradiction[];
  missing_information: string[];
  supporting_event_ids: string[];
  key_event_id: string | null;
  onset: string | null;
  next_step: string;
}

export interface IncidentSummary {
  id: string;
  import_id: string;
  import_name: string;
  ordinal: number;
  title: string;
  severity: IncidentSeverity;
  evidence_status: EvidenceStatus;
  detected_start: string;
  detected_end: string;
  window_start: string;
  window_end: string;
  services: string[];
  error_count: number;
  event_count: number;
  peak_error_ratio: number;
  top_service: string | null;
  top_score: number | null;
  signal_count: number;
}

export interface IncidentDetail extends IncidentSummary {
  evidence_summary: string;
  signals: Signal[];
  hypotheses: Hypothesis[];
  excluded_candidates: { service: string; reason: string }[];
  missing_information: string[];
  data_quality: Signal[];
}

export interface RankingMethod {
  description: string;
  weights: Record<string, number>;
  penalties: Record<string, number>;
}

export interface HypothesesResponse {
  incident_id: string;
  evidence_status: EvidenceStatus;
  evidence_summary: string;
  hypotheses: Hypothesis[];
  excluded_candidates: { service: string; reason: string }[];
  missing_information: string[];
  method: RankingMethod;
}

export interface TimelineItem {
  event: EventRecord;
  category: TimelineCategory;
  is_evidence: boolean;
}

export interface TimelineMarker {
  kind: "detected_start" | "detected_end" | "signal" | "change";
  time: string;
  label: string;
  ref_id: string | null;
}

export interface HistogramBucket {
  start: string;
  errors: number;
  warnings: number;
  other: number;
}

export interface TimelineResponse {
  incident_id: string;
  window_start: string;
  window_end: string;
  total: number;
  limit: number;
  offset: number;
  items: TimelineItem[];
  markers: TimelineMarker[];
  histogram: HistogramBucket[];
  services: string[];
  categories: Record<string, number>;
}

export interface GraphNode {
  id: string;
  kind: "observed" | "inferred";
  status: NodeStatus;
  event_count: number;
  error_count: number;
  warning_count: number;
  error_rate: number | null;
  latency_samples: number;
  p50_ms: number | null;
  p95_ms: number | null;
  versions: string[];
  depth: number | null;
  sample_error_event_ids: string[];
  hypothesis_rank: number | null;
  hypothesis_score: number | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  call_count: number;
  error_count: number;
  error_rate: number | null;
  retry_count: number;
  p50_ms: number | null;
  p95_ms: number | null;
  evidence_types: string[];
  evidence_event_ids: string[];
  in_cycle: boolean;
}

export interface GraphResponse {
  scope: { kind: "incident" | "import"; id: string; start: string | null; end: string | null; event_count: number };
  nodes: GraphNode[];
  edges: GraphEdge[];
  cycles: string[][];
  components: number;
  entry_points: string[];
}

export interface EventDetail {
  event: EventRecord;
  relation: "trace" | "request" | "none";
  related_events: EventRecord[];
  referenced_by: { kind: "hypothesis" | "signal"; ref: string; label: string }[];
}

export type ReplayStatus = "healthy" | "degraded" | "failing";

export interface ReplayFrame {
  index: number;
  event_id: string;
  timestamp: string;
  offset_ms: number;
  service: string;
  target_service: string | null;
  severity: Severity;
  category: TimelineCategory;
  message: string;
  node_updates: Record<string, ReplayStatus>;
  error_totals: Record<string, number>;
  edge: { id: string; failed: boolean } | null;
}

export interface ReplayResponse {
  replay_id: string;
  incident_id: string;
  frame_count: number;
  total_events: number;
  start: string | null;
  end: string | null;
  filters: { services: string[]; severities: string[]; categories: string[] };
  nodes: { id: string; kind: "observed" | "inferred"; depth: number | null }[];
  edges: { id: string; source: string; target: string }[];
  initial_state: Record<string, ReplayStatus>;
  health_rules: Record<string, string | number>;
  frames: ReplayFrame[];
}

export interface ReplayRequest {
  services?: string[];
  severities?: Severity[];
  categories?: TimelineCategory[];
}

export interface ExecutionRef {
  import_id: string;
  incident_id?: string | null;
  start?: string | null;
  end?: string | null;
  label?: string | null;
}

export interface ServiceDiff {
  service: string;
  presence: "both" | "baseline_only" | "target_only";
  baseline_events_per_min: number | null;
  target_events_per_min: number | null;
  baseline_error_rate: number | null;
  target_error_rate: number | null;
  error_rate_delta: number | null;
  baseline_p95_ms: number | null;
  target_p95_ms: number | null;
  p95_ratio: number | null;
  latency_note: string | null;
  baseline_versions: string[];
  target_versions: string[];
  baseline_status: string | null;
  target_status: string | null;
}

export interface ComparisonResult {
  id: string;
  created_at: string;
  baseline_ref: ExecutionRef;
  target_ref: ExecutionRef;
  comparable: boolean;
  incomparable_reasons: string[];
  warnings: string[];
  service_overlap: number;
  baseline: { label: string; start: string | null; end: string | null; event_count: number; error_count: number; minutes: number; service_count: number };
  target: { label: string; start: string | null; end: string | null; event_count: number; error_count: number; minutes: number; service_count: number };
  overall: {
    baseline_error_rate: number | null;
    target_error_rate: number | null;
    error_rate_delta: number | null;
    baseline_events_per_min: number | null;
    target_events_per_min: number | null;
  };
  services: ServiceDiff[];
  edges: {
    id: string;
    presence: "both" | "baseline_only" | "target_only";
    baseline_calls: number;
    target_calls: number;
    baseline_error_rate: number | null;
    target_error_rate: number | null;
  }[];
  findings: { kind: string; service: string; magnitude: number; text: string }[];
}

export interface Report {
  id: string;
  incident_id: string;
  import_id: string;
  comparison_id: string | null;
  format: "markdown" | "json";
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  referenced_event_count: number;
  created_at: string;
  download_url: string;
  content: string | null;
}

export interface Explanation {
  incident_id: string;
  generated_at: string;
  source: "ai" | "deterministic";
  provider: string | null;
  model: string | null;
  label: string;
  disclosure: string;
  raw_event_messages_sent: boolean;
  fallback_reason: string | null;
  summary: string;
  investigation_steps: { step: string; evidence_event_ids: string[] }[];
  cited_event_ids: string[];
}

export interface DashboardSummary {
  import_count: number;
  event_count: number;
  rejected_record_count: number;
  incident_count: number;
  incidents_by_severity: Record<string, number>;
  incidents_by_evidence_status: Record<string, number>;
  top_ranked_services: Record<string, number>;
  average_analysis_ms: number | null;
  recent_incidents: IncidentSummary[];
  recent_imports: {
    id: string;
    name: string;
    status: string;
    created_at: string;
    accepted: number;
    rejected: number;
    incident_count: number;
  }[];
}

export interface AppSettings {
  version: string;
  environment: string;
  database_backend: string;
  max_upload_bytes: number;
  max_records_per_import: number;
  retention_hours: number;
  rate_limit_per_minute: number;
  cors_origins: string[];
  ai_provider: string;
  ai_enabled: boolean;
  ai_model: string | null;
  ai_send_event_messages: boolean;
}

export interface Readiness {
  status: "ready" | "not_ready";
  checks: { name: string; ok: boolean; detail: string }[];
}
