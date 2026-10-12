import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy, useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { EmptyState, Loading } from "./components/ui";
import { ComparisonPage } from "./features/comparison/ComparisonPage";
import { IncidentPickerPage, IncidentsPage } from "./features/incidents/IncidentsPage";
import { IncidentWorkspace } from "./features/incidents/IncidentWorkspace";
import { OverviewTab } from "./features/incidents/OverviewTab";
import { ImportPage } from "./features/ingestion/ImportPage";
import { HelpPage } from "./pages/HelpPage";
import { SettingsPage } from "./pages/SettingsPage";

// Chart- and graph-heavy views are split into separate chunks.
const DashboardPage = lazy(() => import("./features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const GraphPage = lazy(() => import("./pages/GraphPage").then((m) => ({ default: m.GraphPage })));
const TimelineTab = lazy(() => import("./features/incidents/tabs").then((m) => ({ default: m.TimelineTab })));
const GraphTab = lazy(() => import("./features/incidents/tabs").then((m) => ({ default: m.GraphTab })));
const ReplayTab = lazy(() => import("./features/incidents/tabs").then((m) => ({ default: m.ReplayTab })));
const ReportTab = lazy(() => import("./features/incidents/tabs").then((m) => ({ default: m.ReportTab })));

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 15_000, retry: (count, error) => count < 1 && !(error instanceof Error && "status" in error && (error as { status: number }).status === 404), refetchOnWindowFocus: false },
    },
  });
}

export function AppRoutes() {
  return (
    <Suspense fallback={<Loading />}>
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:incidentId" element={<IncidentWorkspace />}>
          <Route index element={<OverviewTab />} />
          <Route path="timeline" element={<TimelineTab />} />
          <Route path="graph" element={<GraphTab />} />
          <Route path="replay" element={<ReplayTab />} />
          <Route path="report" element={<ReportTab />} />
        </Route>
        <Route path="timeline" element={<IncidentPickerPage title="Timeline" description="Pick an incident to inspect its chronological events, markers and evidence." tab="timeline" />} />
        <Route path="graph" element={<GraphPage />} />
        <Route path="replay" element={<IncidentPickerPage title="Replay" description="Pick an incident to replay its events step by step with synchronised service health." tab="replay" />} />
        <Route path="compare" element={<ComparisonPage />} />
        <Route path="reports" element={<IncidentPickerPage title="Reports" description="Pick an incident to generate and export a JSON or Markdown report." tab="report" />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="help" element={<HelpPage />} />
        <Route
          path="*"
          element={<EmptyState title="Page not found" action={<Link to="/" className="text-sm font-medium text-accent-700">Back to the dashboard</Link>} />}
        />
      </Route>
    </Routes>
    </Suspense>
  );
}

export function App() {
  const [client] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
