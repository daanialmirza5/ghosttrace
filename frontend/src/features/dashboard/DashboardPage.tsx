import { ArrowRight, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Badge, Card, EmptyState, ErrorState, EvidenceBadge, Loading, PageHeader, SeverityBadge, Stat } from "../../components/ui";
import { useDashboard } from "../../hooks/queries";
import { formatDateTime, formatNumber } from "../../lib/format";

const SEVERITIES = ["critical", "major", "minor"] as const;

export function DashboardPage() {
  const { data, error, isLoading, refetch } = useDashboard();

  if (isLoading) return <Loading label="Loading dashboard…" />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  const severityData = SEVERITIES.map((severity) => ({ severity, incidents: data.incidents_by_severity[severity] ?? 0 }));
  const statuses = Object.entries(data.incidents_by_evidence_status);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Values on this page are computed by the backend from the imports currently stored. Nothing here is a placeholder."
        actions={
          <Link to="/import" className="inline-flex items-center gap-2 rounded-lg bg-accent-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-accent-700">
            <Upload className="h-4 w-4" aria-hidden /> Import events
          </Link>
        }
      />

      {data.import_count === 0 ? (
        <Card>
          <EmptyState
            title="No data imported yet"
            description="Import a JSONL, JSON or CSV file of application events, or load one of the bundled synthetic incident datasets to explore GhostTrace."
            action={
              <Link to="/import" className="text-sm font-medium text-accent-700 hover:underline">
                Go to the import workspace →
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Imports" value={formatNumber(data.import_count)} hint={`${formatNumber(data.rejected_record_count)} records rejected during validation`} />
            <Stat label="Stored events" value={formatNumber(data.event_count)} />
            <Stat label="Detected incidents" value={formatNumber(data.incident_count)} hint={statuses.map(([k, v]) => `${v} ${k}`).join(" · ") || "none"} />
            <Stat
              label="Mean analysis time"
              value={data.average_analysis_ms === null ? "—" : `${data.average_analysis_ms.toFixed(0)} ms`}
              hint="Correlation, detection, graph and ranking per import"
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card title="Recent incidents" className="lg:col-span-2" padded={false}>
              {data.recent_incidents.length === 0 ? (
                <EmptyState title="No incidents detected" description="The analysed imports contain no anomalous signals." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Incident</th>
                      <th>Severity</th>
                      <th>Evidence</th>
                      <th>Leading hypothesis</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_incidents.map((incident) => (
                      <tr key={incident.id} className="hover:bg-slate-50">
                        <td>
                          <Link to={`/incidents/${incident.id}`} className="font-medium text-slate-900 hover:text-accent-700">
                            {incident.title}
                          </Link>
                          <p className="text-xs text-slate-500">
                            {incident.import_name} · {formatDateTime(incident.detected_start)}
                          </p>
                        </td>
                        <td>
                          <SeverityBadge severity={incident.severity} />
                        </td>
                        <td>
                          <EvidenceBadge status={incident.evidence_status} />
                        </td>
                        <td className="text-sm">
                          {incident.top_service ? (
                            <span>
                              {incident.top_service} <span className="font-mono text-xs text-slate-500">{incident.top_score?.toFixed(2)}</span>
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>

            <Card title="Incidents by severity">
              <div className="h-48" aria-label="Incidents by severity chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={severityData} margin={{ left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="severity" tick={{ fontSize: 12 }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                    <Tooltip />
                    <Bar dataKey="incidents" fill="#6366f1" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-4">
                <p className="label mb-2">Most frequent top-ranked services</p>
                {Object.keys(data.top_ranked_services).length === 0 ? (
                  <p className="text-sm text-slate-500">None with sufficient evidence.</p>
                ) : (
                  <ul className="space-y-1">
                    {Object.entries(data.top_ranked_services).map(([service, count]) => (
                      <li key={service} className="flex justify-between text-sm">
                        <span>{service}</span>
                        <Badge>{count}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>
          </div>

          <Card title="Recent imports" padded={false} actions={<Link to="/import" className="text-xs font-medium text-accent-700">View all <ArrowRight className="inline h-3 w-3" /></Link>}>
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th className="text-right">Accepted</th>
                  <th className="text-right">Rejected</th>
                  <th className="text-right">Incidents</th>
                  <th>Imported</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_imports.map((item) => (
                  <tr key={item.id}>
                    <td className="font-medium">{item.name}</td>
                    <td>
                      <Badge tone={item.status === "completed" ? "green" : item.status === "failed" ? "red" : "amber"}>{item.status.replace(/_/g, " ")}</Badge>
                    </td>
                    <td className="text-right tabular-nums">{formatNumber(item.accepted)}</td>
                    <td className="text-right tabular-nums">{formatNumber(item.rejected)}</td>
                    <td className="text-right tabular-nums">
                      {item.incident_count > 0 ? <Link to={`/incidents?import_id=${item.id}`} className="text-accent-700 hover:underline">{item.incident_count}</Link> : 0}
                    </td>
                    <td className="text-slate-500">{formatDateTime(item.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </>
  );
}
