import { useState } from "react";

import { EventChip, useEventInspector } from "../../components/EventInspector";
import { Badge, Card, EmptyState, ErrorState, Loading, StatusDot } from "../../components/ui";
import { useTimeline } from "../../hooks/queries";
import { formatMs, formatPercent, formatTime } from "../../lib/format";
import type { GraphResponse } from "../../types/api";
import { ServiceGraph } from "./ServiceGraph";

function ServiceEvents({ incidentId, service }: { incidentId: string; service: string }) {
  const { openEvent } = useEventInspector();
  const { data, error, isLoading } = useTimeline(incidentId, { service: [service], severity: ["error", "critical", "warning"], limit: 15 });
  if (isLoading) return <Loading />;
  if (error) return <ErrorState error={error} />;
  if (!data || data.items.length === 0) return <p className="text-xs text-slate-500">No warnings or errors from this service in the incident window.</p>;
  return (
    <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
      {data.items.map(({ event }) => (
        <li key={event.event_id}>
          <button type="button" className="w-full px-2 py-1.5 text-left text-xs hover:bg-slate-50" onClick={() => openEvent(event.event_id)}>
            <span className="font-mono text-slate-500">{formatTime(event.timestamp)}</span> <span className="text-slate-700">{event.message}</span>
          </button>
        </li>
      ))}
      {data.total > data.items.length && <li className="px-2 py-1.5 text-[11px] text-slate-500">+{data.total - data.items.length} more in the Timeline tab</li>}
    </ul>
  );
}

export function GraphExplorer({ graph, incidentId }: { graph: GraphResponse; incidentId?: string }) {
  const [selected, setSelected] = useState<{ kind: "node" | "edge"; id: string } | null>(null);
  if (graph.nodes.length === 0) return <Card><EmptyState title="No services in this scope" /></Card>;
  const node = selected?.kind === "node" ? graph.nodes.find((n) => n.id === selected.id) : undefined;
  const edge = selected?.kind === "edge" ? graph.edges.find((e) => e.id === selected.id) : undefined;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <div>
        <ServiceGraph
          nodes={graph.nodes}
          edges={graph.edges}
          selectedId={selected?.kind === "node" ? selected.id : null}
          onSelectNode={(id) => setSelected({ kind: "node", id })}
          onSelectEdge={(id) => setSelected({ kind: "edge", id })}
        />
        <p className="mt-2 text-xs text-slate-500">
          {graph.nodes.length} services, {graph.edges.length} observed dependencies, {graph.components} connected component{graph.components === 1 ? "" : "s"}
          {graph.cycles.length > 0 && `, ${graph.cycles.length} cycle(s): ${graph.cycles.map((c) => c.join(" → ")).join("; ")}`}. Edges come only from trace ancestry and recorded
          target_service calls, never from timing alone. Dashed nodes are inferred (they emit no events).
        </p>
      </div>
      <Card title={node ? node.id : edge ? edge.id.replace("->", " → ") : "Details"}>
        {!node && !edge && <p className="text-sm text-slate-500">Select a service or a dependency to inspect its evidence.</p>}
        {node && (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <StatusDot status={node.status} />
              <Badge>{node.kind}</Badge>
              {node.hypothesis_rank !== null && <Badge tone="accent">Hypothesis #{node.hypothesis_rank} · {node.hypothesis_score?.toFixed(2)}</Badge>}
            </div>
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <dt className="text-slate-500">Events</dt>
              <dd>{node.event_count}</dd>
              <dt className="text-slate-500">Errors / warnings</dt>
              <dd>
                {node.error_count} / {node.warning_count}
              </dd>
              <dt className="text-slate-500">Error rate</dt>
              <dd>{formatPercent(node.error_rate)}</dd>
              <dt className="text-slate-500">Latency p50 / p95</dt>
              <dd>
                {formatMs(node.p50_ms)} / {formatMs(node.p95_ms)}
              </dd>
              <dt className="text-slate-500">Latency samples</dt>
              <dd>{node.latency_samples}</dd>
              <dt className="text-slate-500">Versions</dt>
              <dd>{node.versions.join(", ") || "—"}</dd>
            </dl>
            {node.sample_error_event_ids.length > 0 && (
              <div>
                <p className="label mb-1">First errors</p>
                <div className="flex flex-wrap gap-1">
                  {node.sample_error_event_ids.map((id) => (
                    <EventChip key={id} id={id} />
                  ))}
                </div>
              </div>
            )}
            {incidentId && node.kind === "observed" && (
              <div>
                <p className="label mb-1">Warnings and errors</p>
                <ServiceEvents incidentId={incidentId} service={node.id} />
              </div>
            )}
          </div>
        )}
        {edge && (
          <div className="space-y-3 text-sm">
            <dl className="grid grid-cols-2 gap-2 text-xs">
              <dt className="text-slate-500">Calls</dt>
              <dd>{edge.call_count}</dd>
              <dt className="text-slate-500">Failed calls</dt>
              <dd>
                {edge.error_count} ({formatPercent(edge.error_rate)})
              </dd>
              <dt className="text-slate-500">Retries</dt>
              <dd>{edge.retry_count}</dd>
              <dt className="text-slate-500">Latency p50 / p95</dt>
              <dd>
                {formatMs(edge.p50_ms)} / {formatMs(edge.p95_ms)}
              </dd>
              <dt className="text-slate-500">Evidence type</dt>
              <dd>{edge.evidence_types.join(", ")}</dd>
            </dl>
            <div>
              <p className="label mb-1">Evidence events</p>
              <div className="flex flex-wrap gap-1">
                {edge.evidence_event_ids.slice(0, 12).map((id) => (
                  <EventChip key={id} id={id} />
                ))}
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
