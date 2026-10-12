import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Button, Card, EmptyState, ErrorState, EvidenceBadge, Loading, PageHeader, SeverityBadge } from "../../components/ui";
import { useIncidents } from "../../hooks/queries";
import { durationBetween, formatDateTime, formatNumber } from "../../lib/format";

export function IncidentTable({ importId, severity, evidenceStatus, linkTo }: { importId?: string; severity?: string; evidenceStatus?: string; linkTo?: (id: string) => string }) {
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading, refetch } = useIncidents({
    import_id: importId || undefined,
    severity: severity || undefined,
    evidence_status: evidenceStatus || undefined,
    limit: 20,
    offset,
  });
  if (isLoading) return <Loading label="Loading incidents…" />;
  if (error) return <div className="p-4"><ErrorState error={error} onRetry={() => void refetch()} /></div>;
  if (!data || data.items.length === 0)
    return (
      <EmptyState
        title="No incidents match"
        description="Incidents are created automatically when an import contains anomalous signals."
        action={<Link to="/import" className="text-sm font-medium text-accent-700">Import events →</Link>}
      />
    );
  const target = linkTo ?? ((id: string) => `/incidents/${id}`);
  return (
    <>
      <div className="overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>Incident</th>
              <th>Severity</th>
              <th>Evidence</th>
              <th>Leading hypothesis</th>
              <th className="text-right">Errors</th>
              <th>Detected</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((incident) => (
              <tr key={incident.id} className="hover:bg-slate-50">
                <td>
                  <Link to={target(incident.id)} className="font-medium text-slate-900 hover:text-accent-700">
                    {incident.title}
                  </Link>
                  <p className="text-xs text-slate-500">
                    {incident.import_name} · {incident.services.length} services · {incident.signal_count} signals
                  </p>
                </td>
                <td>
                  <SeverityBadge severity={incident.severity} />
                </td>
                <td>
                  <EvidenceBadge status={incident.evidence_status} />
                </td>
                <td className="text-sm">
                  {incident.top_service ?? "—"}
                  {incident.top_score !== null && <span className="ml-1 font-mono text-xs text-slate-500">{incident.top_score.toFixed(2)}</span>}
                </td>
                <td className="text-right tabular-nums">{formatNumber(incident.error_count)}</td>
                <td className="text-xs text-slate-500">
                  {formatDateTime(incident.detected_start)}
                  <br />
                  for {durationBetween(incident.detected_start, incident.detected_end)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between px-4 py-2 text-xs text-slate-500">
        <span>
          {offset + 1}–{offset + data.items.length} of {data.total}
        </span>
        <div className="flex gap-2">
          <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>
            Previous
          </Button>
          <Button size="sm" disabled={offset + 20 >= data.total} onClick={() => setOffset(offset + 20)}>
            Next
          </Button>
        </div>
      </div>
    </>
  );
}

export function IncidentsPage() {
  const [params, setParams] = useSearchParams();
  const importId = params.get("import_id") ?? "";
  const severity = params.get("severity") ?? "";
  const evidence = params.get("evidence_status") ?? "";
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };
  return (
    <>
      <PageHeader title="Incidents" description="Each incident groups observed signals that overlap in time. Open one to review ranked, evidence-linked hypotheses." />
      <Card
        padded={false}
        title="Detected incidents"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {importId && (
              <Button size="sm" variant="ghost" onClick={() => update("import_id", "")}>
                Import {importId} ✕
              </Button>
            )}
            <select aria-label="Filter by severity" className="input w-36 py-1" value={severity} onChange={(e) => update("severity", e.target.value)}>
              <option value="">All severities</option>
              <option value="critical">Critical</option>
              <option value="major">Major</option>
              <option value="minor">Minor</option>
            </select>
            <select aria-label="Filter by evidence status" className="input w-44 py-1" value={evidence} onChange={(e) => update("evidence_status", e.target.value)}>
              <option value="">Any evidence status</option>
              <option value="sufficient">Sufficient</option>
              <option value="ambiguous">Ambiguous</option>
              <option value="insufficient">Insufficient</option>
            </select>
          </div>
        }
      >
        <IncidentTable importId={importId} severity={severity} evidenceStatus={evidence} />
      </Card>
    </>
  );
}

/** Used by the standalone Timeline / Graph / Replay / Reports pages. */
export function IncidentPickerPage({ title, description, tab }: { title: string; description: string; tab: string }) {
  const navigate = useNavigate();
  return (
    <>
      <PageHeader title={title} description={description} />
      <Card title="Choose an incident" padded={false}>
        <IncidentTable linkTo={(id) => `/incidents/${id}/${tab}`} />
      </Card>
      <p className="mt-4 text-xs text-slate-500">
        Tip: you can also open an incident and switch tabs.{" "}
        <button type="button" className="text-accent-700 hover:underline" onClick={() => navigate("/import")}>
          Import more data
        </button>
      </p>
    </>
  );
}
