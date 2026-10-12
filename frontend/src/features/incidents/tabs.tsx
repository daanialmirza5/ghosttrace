import { ErrorState, Loading } from "../../components/ui";
import { useIncidentGraph } from "../../hooks/queries";
import { GraphExplorer } from "../dependency-graph/GraphExplorer";
import { ReplayView } from "../replay/ReplayView";
import { ReportPanel } from "../reports/ReportPanel";
import { TimelineView } from "../timeline/TimelineView";
import { useWorkspaceIncident } from "./IncidentWorkspace";

export function TimelineTab() {
  return <TimelineView incident={useWorkspaceIncident()} />;
}

export function GraphTab() {
  const incident = useWorkspaceIncident();
  const { data, error, isLoading, refetch } = useIncidentGraph(incident.id);
  if (isLoading) return <Loading label="Building graph…" />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  return data ? <GraphExplorer graph={data} incidentId={incident.id} /> : null;
}

export function ReplayTab() {
  return <ReplayView incident={useWorkspaceIncident()} />;
}

export function ReportTab() {
  return <ReportPanel incident={useWorkspaceIncident()} />;
}
