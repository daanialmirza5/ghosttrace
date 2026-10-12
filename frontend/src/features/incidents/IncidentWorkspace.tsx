import { ArrowLeft } from "lucide-react";
import { Suspense } from "react";
import { Link, NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";

import { EventInspectorProvider } from "../../components/EventInspector";
import { Badge, ErrorState, EvidenceBadge, Loading, SeverityBadge, cx } from "../../components/ui";
import { useIncident } from "../../hooks/queries";
import { durationBetween, formatDateTime, formatNumber } from "../../lib/format";
import type { IncidentDetail } from "../../types/api";

const TABS = [
  { to: "", label: "Overview", end: true },
  { to: "timeline", label: "Timeline" },
  { to: "graph", label: "Service graph" },
  { to: "replay", label: "Replay" },
  { to: "report", label: "Report" },
];

export function useWorkspaceIncident(): IncidentDetail {
  return useOutletContext<IncidentDetail>();
}

export function IncidentWorkspace() {
  const { incidentId = "" } = useParams();
  const { data, error, isLoading, refetch } = useIncident(incidentId);

  if (isLoading) return <Loading label="Loading incident…" />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  return (
    <EventInspectorProvider incidentId={data.id}>
      <div className="mb-4">
        <Link to="/incidents" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800">
          <ArrowLeft className="h-3 w-3" aria-hidden /> All incidents
        </Link>
      </div>
      <header className="mb-5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">{data.title}</h1>
          <SeverityBadge severity={data.severity} />
          <EvidenceBadge status={data.evidence_status} />
        </div>
        <p className="mt-1 text-sm text-slate-600">
          {formatDateTime(data.detected_start)} · {durationBetween(data.detected_start, data.detected_end)} · {formatNumber(data.error_count)} errors in{" "}
          {formatNumber(data.event_count)} window events · import <Link className="text-accent-700 hover:underline" to={`/incidents?import_id=${data.import_id}`}>{data.import_name}</Link>
        </p>
        <div className="mt-2 flex flex-wrap gap-1">
          {data.services.map((service) => (
            <Badge key={service}>{service}</Badge>
          ))}
        </div>
      </header>
      <nav aria-label="Incident sections" className="mb-5 flex gap-1 overflow-x-auto border-b border-slate-200">
        {TABS.map((tab) => (
          <NavLink
            key={tab.label}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              cx("-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap", isActive ? "border-accent-600 font-medium text-accent-700" : "border-transparent text-slate-600 hover:text-slate-900")
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <Suspense fallback={<Loading />}>
        <Outlet context={data} />
      </Suspense>
    </EventInspectorProvider>
  );
}
