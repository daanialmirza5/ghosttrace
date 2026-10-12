import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type UploadOptions } from "../services/api";
import type { ExecutionRef, ReplayRequest } from "../types/api";

export const keys = {
  dashboard: ["dashboard"] as const,
  imports: (params: object) => ["imports", params] as const,
  incidents: (params: object) => ["incidents", params] as const,
  incident: (id: string) => ["incident", id] as const,
  hypotheses: (id: string) => ["incident", id, "hypotheses"] as const,
  timeline: (id: string, params: object) => ["incident", id, "timeline", params] as const,
  graph: (id: string) => ["incident", id, "graph"] as const,
  importGraph: (id: string) => ["import", id, "graph"] as const,
  event: (id: string, eventId: string) => ["incident", id, "event", eventId] as const,
  reports: (id: string) => ["incident", id, "reports"] as const,
};

export const useDashboard = () => useQuery({ queryKey: keys.dashboard, queryFn: api.dashboard });
export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: api.settings });
export const useReadiness = () => useQuery({ queryKey: ["ready"], queryFn: api.ready, retry: false });
export const useDemoDatasets = () => useQuery({ queryKey: ["demo-datasets"], queryFn: api.listDemoDatasets });

export const useImports = (params: { limit?: number; offset?: number } = {}) =>
  useQuery({ queryKey: keys.imports(params), queryFn: () => api.listImports(params), placeholderData: keepPreviousData });

export const useIncidents = (params: { import_id?: string; severity?: string; evidence_status?: string; limit?: number; offset?: number } = {}) =>
  useQuery({ queryKey: keys.incidents(params), queryFn: () => api.listIncidents(params), placeholderData: keepPreviousData });

export const useIncident = (id: string) => useQuery({ queryKey: keys.incident(id), queryFn: () => api.getIncident(id) });
export const useHypotheses = (id: string) => useQuery({ queryKey: keys.hypotheses(id), queryFn: () => api.getHypotheses(id) });
export const useIncidentGraph = (id: string) => useQuery({ queryKey: keys.graph(id), queryFn: () => api.getIncidentGraph(id) });
export const useImportGraph = (id: string | undefined) =>
  useQuery({ queryKey: keys.importGraph(id ?? ""), queryFn: () => api.importGraph(id!), enabled: Boolean(id) });

export const useTimeline = (id: string, params: Record<string, string | number | boolean | string[] | undefined>) =>
  useQuery({ queryKey: keys.timeline(id, params), queryFn: () => api.getTimeline(id, params), placeholderData: keepPreviousData });

export const useIncidentEvent = (id: string | null, eventId: string | null) =>
  useQuery({
    queryKey: keys.event(id ?? "", eventId ?? ""),
    queryFn: () => api.getIncidentEvent(id!, eventId!),
    enabled: Boolean(id && eventId),
  });

export const useReports = (id: string) => useQuery({ queryKey: keys.reports(id), queryFn: () => api.listReports(id) });

export function useUploadImport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, options }: { file: File; options: UploadOptions }) => api.uploadImport(file, options),
    onSuccess: () => client.invalidateQueries(),
  });
}

export function useImportDemo() {
  const client = useQueryClient();
  return useMutation({ mutationFn: api.importDemo, onSuccess: () => client.invalidateQueries() });
}

export function useDeleteImport() {
  const client = useQueryClient();
  return useMutation({ mutationFn: api.deleteImport, onSuccess: () => client.invalidateQueries() });
}

export const useReplay = (id: string) =>
  useMutation({ mutationFn: (body: ReplayRequest) => api.createReplay(id, body) });

export const useExplanation = (id: string) => useMutation({ mutationFn: () => api.createExplanation(id) });

export function useComparison() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ baseline, target }: { baseline: ExecutionRef; target: ExecutionRef }) => api.createComparison(baseline, target),
    onSuccess: () => client.invalidateQueries({ queryKey: ["comparisons"] }),
  });
}

export const useComparisons = () => useQuery({ queryKey: ["comparisons"], queryFn: api.listComparisons });

export function useCreateReport(incidentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ format, comparisonId }: { format: "markdown" | "json"; comparisonId?: string | null }) =>
      api.createReport(incidentId, format, comparisonId),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.reports(incidentId) }),
  });
}
