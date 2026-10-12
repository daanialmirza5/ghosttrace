import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ComparisonPage, ComparisonResultView } from "../features/comparison/ComparisonPage";
import type { ComparisonResult } from "../types/api";
import { importSummary } from "./fixtures";
import { mockApi, renderWithProviders } from "./utils";

const result = (overrides: Partial<ComparisonResult> = {}): ComparisonResult => ({
  id: "cmp_1",
  created_at: "2026-03-14T10:00:00Z",
  baseline_ref: { import_id: "imp_h" },
  target_ref: { import_id: "imp_f" },
  comparable: true,
  incomparable_reasons: [],
  warnings: ["window lengths differ by 3.5x; rates are normalised per minute"],
  service_overlap: 1,
  baseline: { label: "healthy", start: null, end: null, event_count: 2283, error_count: 12, minutes: 10, service_count: 8 },
  target: { label: "failed", start: null, end: null, event_count: 2181, error_count: 125, minutes: 10, service_count: 8 },
  overall: { baseline_error_rate: 0.005, target_error_rate: 0.057, error_rate_delta: 0.052, baseline_events_per_min: 228, target_events_per_min: 218 },
  services: [
    {
      service: "inventory-service",
      presence: "both",
      baseline_events_per_min: 50,
      target_events_per_min: 48,
      baseline_error_rate: 0.001,
      target_error_rate: 0.12,
      error_rate_delta: 0.119,
      baseline_p95_ms: null,
      target_p95_ms: null,
      p95_ratio: null,
      latency_note: "not measured in either execution",
      baseline_versions: ["2.3.1"],
      target_versions: ["2.3.1", "2.4.0"],
      baseline_status: "healthy",
      target_status: "failing",
    },
  ],
  edges: [],
  findings: [{ kind: "error_rate", service: "inventory-service", magnitude: 0.12, text: "inventory-service error rate 0.1% -> 12.0%" }],
  ...overrides,
});

test("renders findings, warnings and missing measurements explicitly", () => {
  renderWithProviders(<ComparisonResultView result={result()} />);
  expect(screen.getByText("Executions are comparable")).toBeInTheDocument();
  expect(screen.getByText(/rates are normalised per minute/)).toBeInTheDocument();
  expect(screen.getByText("inventory-service error rate 0.1% -> 12.0%")).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "Per-service comparison" });
  expect(within(table).getByText("not measured in either execution")).toBeInTheDocument();
  expect(within(table).getByText("2.3.1 → 2.3.1, 2.4.0")).toBeInTheDocument();
});

test("incomparable executions are flagged with reasons", () => {
  renderWithProviders(<ComparisonResultView result={result({ comparable: false, incomparable_reasons: ["service sets barely overlap"], findings: [] })} />);
  expect(screen.getByText("Executions are not comparable")).toBeInTheDocument();
  expect(screen.getByText("service sets barely overlap")).toBeInTheDocument();
});

test("defaults to a healthy baseline and failed target, then submits", async () => {
  const { calls } = mockApi({
    "GET /imports": { items: [importSummary({ id: "imp_h", name: "healthy", incident_count: 0 }), importSummary({ id: "imp_f", name: "failed", incident_count: 1 })], total: 2, limit: 100, offset: 0 },
    "GET /incidents": { items: [], total: 0, limit: 50, offset: 0 },
    "POST /comparisons": { status: 201, body: result() },
  });
  renderWithProviders(<ComparisonPage />);
  await userEvent.click(await screen.findByRole("button", { name: "Compare executions" }));
  expect(await screen.findByText("Notable differences")).toBeInTheDocument();
  const body = JSON.parse(String(calls.find((call) => call.method === "POST")!.init!.body));
  expect(body.baseline.import_id).toBe("imp_h");
  expect(body.target.import_id).toBe("imp_f");
});
