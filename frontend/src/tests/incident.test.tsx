import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";

import { IncidentWorkspace } from "../features/incidents/IncidentWorkspace";
import { OverviewTab } from "../features/incidents/OverviewTab";
import { ReportTab } from "../features/incidents/tabs";
import { event, incident } from "./fixtures";
import { mockApi, renderWithProviders } from "./utils";

function Workspace() {
  return (
    <Routes>
      <Route path="/incidents/:incidentId" element={<IncidentWorkspace />}>
        <Route index element={<OverviewTab />} />
        <Route path="report" element={<ReportTab />} />
      </Route>
    </Routes>
  );
}

const routes = {
  "GET /incidents/inc_1": incident(),
  "GET /incidents/inc_1/hypotheses": { method: { description: "Weighted sum. Not a probability.", weights: { temporal_precedence: 0.2 }, penalties: {} } },
  "GET /incidents/inc_1/events/ev-1": {
    event: event(),
    relation: "none",
    related_events: [],
    referenced_by: [{ kind: "hypothesis", ref: "1", label: "Hypothesis #1 (redis-cache): temporal_precedence" }],
  },
};

test("renders ranked hypotheses with scoring signals and labels", async () => {
  mockApi(routes);
  renderWithProviders(<Workspace />, { route: "/incidents/inc_1" });
  expect(await screen.findByRole("heading", { name: "redis-cache" })).toBeInTheDocument();
  expect(screen.getAllByText("heuristic score (not a probability)")[0]).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "Scoring signals for redis-cache" });
  expect(within(table).getByText("Temporal precedence")).toBeInTheDocument();
  expect(within(table).getByText("earliest sustained anomaly among candidates")).toBeInTheDocument();
  expect(screen.getByText(/Ruled out: web-frontend/)).toBeInTheDocument();
  expect(screen.getAllByText("Evidence sufficient").length).toBeGreaterThan(0);
});

test("clicking an event ID opens the evidence drawer and Escape closes it", async () => {
  const { calls } = mockApi(routes);
  renderWithProviders(<Workspace />, { route: "/incidents/inc_1" });
  const table = await screen.findByRole("table", { name: "Scoring signals for redis-cache" });
  await userEvent.click(within(table).getByRole("button", { name: "ev-1" }));
  const dialog = await screen.findByRole("dialog", { name: "Event ev-1" });
  expect(await within(dialog).findByText("redis-server terminated (OOM)")).toBeInTheDocument();
  expect(within(dialog).getByText("Hypothesis #1 (redis-cache): temporal_precedence")).toBeInTheDocument();
  expect(within(dialog).getByText("8150")).toBeInTheDocument();
  expect(calls.some((call) => call.url.pathname.endsWith("/events/ev-1"))).toBe(true);
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("generates a deterministic explanation on request", async () => {
  mockApi({
    ...routes,
    "POST /incidents/inc_1/explanations": {
      incident_id: "inc_1",
      generated_at: "2026-03-14T10:00:00Z",
      source: "deterministic",
      provider: null,
      model: null,
      label: "Deterministic template",
      disclosure: "Generated from a fixed template.",
      raw_event_messages_sent: false,
      fallback_reason: "AI explanations are disabled",
      summary: "The highest-ranked hypothesis is redis-cache.",
      investigation_steps: [{ step: "Inspect redis-cache.", evidence_event_ids: ["ev-1"] }],
      cited_event_ids: ["ev-1"],
    },
  });
  renderWithProviders(<Workspace />, { route: "/incidents/inc_1" });
  await userEvent.click(await screen.findByRole("button", { name: "Generate" }));
  expect(await screen.findByText("The highest-ranked hypothesis is redis-cache.")).toBeInTheDocument();
  expect(screen.getByText("Deterministic template")).toBeInTheDocument();
  expect(screen.getByText(/Fallback reason: AI explanations are disabled/)).toBeInTheDocument();
});

test("exports a report with a working download link", async () => {
  const report = {
    id: "rep_1",
    incident_id: "inc_1",
    import_id: "imp_1",
    comparison_id: null,
    format: "markdown",
    filename: "ghosttrace-inc_1.md",
    content_type: "text/markdown",
    size_bytes: 40,
    sha256: "b".repeat(64),
    referenced_event_count: 12,
    created_at: "2026-03-14T10:00:00Z",
    download_url: "/api/v1/reports/rep_1/download",
    content: "# Incident report: test",
  };
  const { calls } = mockApi({
    ...routes,
    "GET /incidents/inc_1/reports": [],
    "GET /comparisons": { items: [], total: 0, limit: 20, offset: 0 },
    "POST /incidents/inc_1/reports": { status: 201, body: report },
  });
  renderWithProviders(<Workspace />, { route: "/incidents/inc_1/report" });
  await userEvent.click(await screen.findByRole("button", { name: "Generate report" }));
  expect(await screen.findByTestId("report-preview")).toHaveTextContent("# Incident report: test");
  const link = screen.getByRole("link", { name: /Download Markdown/ });
  expect(link).toHaveAttribute("href", "/api/v1/reports/rep_1/download");
  expect(link).toHaveAttribute("download", "ghosttrace-inc_1.md");
  expect(screen.getByText(/12 event IDs verified/)).toBeInTheDocument();
  const post = calls.find((call) => call.method === "POST")!;
  expect(JSON.parse(String(post.init!.body))).toEqual({ format: "markdown", comparison_id: null });
});

test("unknown incidents show an error", async () => {
  mockApi({});
  renderWithProviders(<Workspace />, { route: "/incidents/inc_missing" });
  expect(await screen.findByRole("alert")).toHaveTextContent("unmocked GET /incidents/inc_missing");
});
