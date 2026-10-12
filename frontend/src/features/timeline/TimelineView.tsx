import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useEventInspector } from "../../components/EventInspector";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, SeverityBadge, cx, type Tone } from "../../components/ui";
import { useTimeline } from "../../hooks/queries";
import { formatMs, formatTime, humanize } from "../../lib/format";
import type { IncidentDetail, TimelineCategory } from "../../types/api";

const PAGE = 200;
export const CATEGORY_TONE: Record<TimelineCategory, Tone> = {
  error: "red",
  warning: "amber",
  request: "slate",
  change: "accent",
  retry: "amber",
  timeout: "red",
  dependency_failure: "red",
  log: "slate",
};
const CATEGORIES = Object.keys(CATEGORY_TONE) as TimelineCategory[];

export function TimelineView({ incident }: { incident: IncidentDetail }) {
  const { openEvent } = useEventInspector();
  const [service, setService] = useState("");
  const [severity, setSeverity] = useState("");
  const [categories, setCategories] = useState<TimelineCategory[]>([]);
  const [evidenceOnly, setEvidenceOnly] = useState(false);
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [offset, setOffset] = useState(0);

  const params = {
    service: service ? [service] : undefined,
    severity: severity ? [severity] : undefined,
    category: categories.length ? categories : undefined,
    evidence_only: evidenceOnly || undefined,
    start: range?.start,
    end: range?.end,
    limit: PAGE,
    offset,
  };
  const { data, error, isLoading, isFetching, refetch } = useTimeline(incident.id, params);

  const histogram = useMemo(
    () => (data?.histogram ?? []).map((bucket) => ({ ...bucket, label: formatTime(bucket.start).slice(0, 8) })),
    [data?.histogram],
  );
  const bucketWidth = useMemo(() => {
    if (!data || data.histogram.length < 2) return 0;
    return new Date(data.histogram[1]!.start).getTime() - new Date(data.histogram[0]!.start).getTime();
  }, [data]);

  const reset = (fn: () => void) => {
    fn();
    setOffset(0);
  };
  const toggleCategory = (category: TimelineCategory) =>
    reset(() => setCategories((current) => (current.includes(category) ? current.filter((item) => item !== category) : [...current, category])));

  if (isLoading) return <Loading label="Loading timeline…" />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  const detectedStart = formatTime(incident.detected_start).slice(0, 8);
  const detectedEnd = formatTime(incident.detected_end).slice(0, 8);
  const nearestLabel = (iso: string) => {
    const target = new Date(iso).getTime();
    let best = histogram[0]?.label;
    for (const bucket of histogram) if (new Date(bucket.start).getTime() <= target) best = bucket.label;
    return best;
  };

  return (
    <div className="space-y-4">
      <Card
        title="Event volume (UTC)"
        actions={range && <Button size="sm" variant="ghost" onClick={() => reset(() => setRange(null))}>Clear time filter</Button>}
      >
        <div className="h-44" aria-label="Event histogram; click a bar to filter to that interval">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={histogram}
              margin={{ left: -20, right: 8 }}
              onClick={(state) => {
                const index = typeof state?.activeTooltipIndex === "number" ? state.activeTooltipIndex : Number(state?.activeTooltipIndex);
                const bucket = Number.isFinite(index) ? histogram[index] : undefined;
                if (!bucket || !bucketWidth) return;
                const start = new Date(bucket.start);
                reset(() => setRange({ start: start.toISOString(), end: new Date(start.getTime() + bucketWidth).toISOString() }));
              }}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={40} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip />
              <ReferenceArea x1={nearestLabel(incident.detected_start)} x2={nearestLabel(incident.detected_end)} fill="#fee2e2" fillOpacity={0.5} label={{ value: "detected", fontSize: 10, position: "insideTopLeft" }} />
              {data.markers
                .filter((marker) => marker.kind === "change")
                .map((marker) => (
                  <ReferenceLine key={`${marker.ref_id}`} x={nearestLabel(marker.time)} stroke="#4f46e5" strokeDasharray="4 2" />
                ))}
              <Bar dataKey="other" stackId="a" fill="#cbd5e1" name="other" />
              <Bar dataKey="warnings" stackId="a" fill="#f59e0b" name="warnings" />
              <Bar dataKey="errors" stackId="a" fill="#ef4444" name="errors" cursor="pointer" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Shaded: detected interval {detectedStart}–{detectedEnd}. Dashed lines: deployment or configuration changes. {range && `Showing ${formatTime(range.start)}–${formatTime(range.end)}.`}
        </p>
      </Card>

      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-3">
          <select aria-label="Filter by service" className="input w-48 py-1" value={service} onChange={(e) => reset(() => setService(e.target.value))}>
            <option value="">All services</option>
            {data.services.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
          <select aria-label="Filter by severity" className="input w-36 py-1" value={severity} onChange={(e) => reset(() => setSeverity(e.target.value))}>
            <option value="">All severities</option>
            {["critical", "error", "warning", "info", "debug"].map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by category">
            {CATEGORIES.map((category) => (
              <button
                key={category}
                type="button"
                aria-pressed={categories.includes(category)}
                onClick={() => toggleCategory(category)}
                className={cx(
                  "rounded-full border px-2 py-0.5 text-xs",
                  categories.includes(category) ? "border-accent-500 bg-accent-50 text-accent-700" : "border-slate-200 text-slate-600 hover:bg-slate-50",
                )}
              >
                {humanize(category)} <span className="text-slate-400">{data.categories[category] ?? 0}</span>
              </button>
            ))}
          </div>
          <label className="ml-auto flex items-center gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={evidenceOnly} onChange={(e) => reset(() => setEvidenceOnly(e.target.checked))} />
            Cited evidence only
          </label>
        </div>
        {data.items.length === 0 ? (
          <EmptyState title="No events match these filters" />
        ) : (
          <ol className={cx("divide-y divide-slate-100", isFetching && "opacity-60")} aria-label="Timeline events">
            {data.items.map(({ event, category, is_evidence }) => (
              <li key={event.event_id}>
                <button type="button" onClick={() => openEvent(event.event_id)} className="grid w-full grid-cols-[6.5rem_9rem_1fr] items-start gap-3 px-4 py-2 text-left hover:bg-slate-50 sm:grid-cols-[6.5rem_10rem_7rem_1fr]">
                  <span className="font-mono text-xs text-slate-500">{formatTime(event.timestamp)}</span>
                  <span className="truncate text-xs font-medium text-slate-800">{event.service}</span>
                  <span className="hidden items-center gap-1 sm:flex">
                    <Badge tone={CATEGORY_TONE[category]}>{humanize(category)}</Badge>
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      <SeverityBadge severity={event.severity} />
                      {is_evidence && <Badge tone="accent">evidence</Badge>}
                      {event.target_service && <span className="text-[11px] text-slate-500">→ {event.target_service}</span>}
                      {event.duration_ms !== null && <span className="text-[11px] text-slate-500">{formatMs(event.duration_ms)}</span>}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-slate-600">{event.message}</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
        )}
        <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
          <span>
            {data.total === 0 ? 0 : offset + 1}–{offset + data.items.length} of {data.total} events
          </span>
          <div className="flex gap-2">
            <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Previous
            </Button>
            <Button size="sm" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
              Next
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
