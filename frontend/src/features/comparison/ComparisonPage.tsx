import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useId, useState } from "react";

import { Badge, Button, Card, EmptyState, ErrorState, Field, Loading, PageHeader } from "../../components/ui";
import { useComparison, useImports, useIncidents } from "../../hooks/queries";
import { formatMs, formatNumber, formatPercent } from "../../lib/format";
import type { ComparisonResult, ExecutionRef, ImportSummary } from "../../types/api";

function ExecutionPicker({ title, imports, value, onChange }: { title: string; imports: ImportSummary[]; value: ExecutionRef; onChange: (ref: ExecutionRef) => void }) {
  const incidents = useIncidents({ import_id: value.import_id || undefined, limit: 50 });
  const ids = { import: useId(), scope: useId(), label: useId() };
  return (
    <fieldset className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      <legend className="px-1 text-sm font-semibold text-slate-800">{title}</legend>
      <Field label="Import" htmlFor={ids.import}>
        <select id={ids.import} className="input" value={value.import_id} onChange={(e) => onChange({ ...value, import_id: e.target.value, incident_id: null })}>
          <option value="">Choose an import…</option>
          {imports.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name} ({item.incident_count} incidents)
            </option>
          ))}
        </select>
      </Field>
      <Field label="Scope" htmlFor={ids.scope}>
        <select id={ids.scope} className="input" value={value.incident_id ?? ""} disabled={!value.import_id} onChange={(e) => onChange({ ...value, incident_id: e.target.value || null })}>
          <option value="">Whole import</option>
          {incidents.data?.items.map((incident) => (
            <option key={incident.id} value={incident.id}>
              Incident window: {incident.title}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Label" htmlFor={ids.label}>
        <input id={ids.label} className="input" value={value.label ?? ""} maxLength={80} onChange={(e) => onChange({ ...value, label: e.target.value })} />
      </Field>
    </fieldset>
  );
}

export function ComparisonResultView({ result }: { result: ComparisonResult }) {
  return (
    <div className="space-y-4">
      <div className={`flex items-start gap-3 rounded-xl border p-4 ${result.comparable ? "border-emerald-200 bg-emerald-50/60" : "border-red-200 bg-red-50/60"}`} role="status">
        {result.comparable ? <CheckCircle2 className="h-5 w-5 text-emerald-600" aria-hidden /> : <AlertTriangle className="h-5 w-5 text-red-600" aria-hidden />}
        <div className="text-sm">
          <p className="font-medium">{result.comparable ? "Executions are comparable" : "Executions are not comparable"}</p>
          {result.incomparable_reasons.map((reason) => (
            <p key={reason} className="text-red-800">{reason}</p>
          ))}
          {result.warnings.map((warning) => (
            <p key={warning} className="text-amber-800">Warning: {warning}</p>
          ))}
          <p className="text-xs text-slate-500">Service overlap (Jaccard): {result.service_overlap.toFixed(2)}</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {[result.baseline, result.target].map((side) => (
          <Card key={side.label} title={side.label}>
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <dt className="text-slate-500">Events</dt>
              <dd className="tabular-nums">{formatNumber(side.event_count)}</dd>
              <dt className="text-slate-500">Errors</dt>
              <dd className="tabular-nums">{formatNumber(side.error_count)}</dd>
              <dt className="text-slate-500">Duration</dt>
              <dd>{side.minutes.toFixed(1)} min</dd>
              <dt className="text-slate-500">Services</dt>
              <dd>{side.service_count}</dd>
            </dl>
          </Card>
        ))}
      </div>

      <Card title="Notable differences">
        {result.findings.length === 0 ? (
          <p className="text-sm text-slate-500">No difference crossed the reporting thresholds.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {result.findings.map((finding) => (
              <li key={`${finding.kind}-${finding.service}-${finding.text}`} className="flex items-start gap-2">
                <Badge tone={finding.kind === "error_rate" || finding.kind === "dependency" ? "red" : finding.kind === "latency" ? "amber" : "accent"}>{finding.kind.replace("_", " ")}</Badge>
                {finding.text}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Per-service comparison" padded={false}>
        <div className="overflow-x-auto">
          <table className="table" aria-label="Per-service comparison">
            <thead>
              <tr>
                <th>Service</th>
                <th className="text-right">Events/min</th>
                <th className="text-right">Error rate</th>
                <th className="text-right">p95 latency</th>
                <th>Versions</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {result.services.map((row) => (
                <tr key={row.service}>
                  <td className="font-medium">
                    {row.service}
                    {row.presence !== "both" && <Badge tone="amber">{row.presence.replace("_", " ")}</Badge>}
                  </td>
                  <td className="text-right text-xs tabular-nums">
                    {row.baseline_events_per_min ?? "—"} → {row.target_events_per_min ?? "—"}
                  </td>
                  <td className="text-right text-xs tabular-nums">
                    {formatPercent(row.baseline_error_rate)} → <span className={(row.error_rate_delta ?? 0) > 0.02 ? "font-semibold text-red-700" : undefined}>{formatPercent(row.target_error_rate)}</span>
                  </td>
                  <td className="text-right text-xs tabular-nums" title={row.latency_note ?? undefined}>
                    {row.latency_note && row.p95_ratio === null ? <span className="text-slate-400">{row.latency_note}</span> : `${formatMs(row.baseline_p95_ms)} → ${formatMs(row.target_p95_ms)}`}
                  </td>
                  <td className="text-xs">
                    {row.baseline_versions.join(", ") || "—"} → {row.target_versions.join(", ") || "—"}
                  </td>
                  <td className="text-xs">
                    {row.baseline_status ?? "—"} → {row.target_status ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

export function ComparisonPage() {
  const imports = useImports({ limit: 100 });
  const compare = useComparison();
  const [chosenBaseline, setBaseline] = useState<ExecutionRef | null>(null);
  const [chosenTarget, setTarget] = useState<ExecutionRef | null>(null);

  const items = imports.data?.items.filter((item) => item.status !== "failed") ?? [];
  // Until the user picks: the largest incident-free import as baseline, the newest import
  // with incidents as target.
  const healthy = items
    .filter((item) => item.incident_count === 0)
    .reduce<ImportSummary | undefined>((best, item) => (!best || item.accepted > best.accepted ? item : best), undefined);
  const failed = items.find((item) => item.incident_count > 0);
  const baseline = chosenBaseline ?? { import_id: healthy?.id ?? "", label: healthy ? "healthy" : "baseline" };
  const target = chosenTarget ?? { import_id: failed?.id ?? "", label: failed ? "failed" : "target" };

  return (
    <>
      <PageHeader title="Healthy vs failed comparison" description="Compare two executions: rates are normalised per minute, latency is only compared where both sides measured it, and incomparable inputs are reported rather than silently diffed." />
      {imports.isLoading && <Loading />}
      {imports.error && <ErrorState error={imports.error} />}
      {imports.data && items.length < 1 && (
        <Card>
          <EmptyState title="Import at least one dataset to compare" description="For example, import the healthy control and one incident dataset." />
        </Card>
      )}
      {items.length > 0 && (
        <form
          className="mb-6 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            compare.mutate({ baseline, target });
          }}
        >
          <div className="grid gap-4 md:grid-cols-2">
            <ExecutionPicker title="Baseline (e.g. healthy)" imports={items} value={baseline} onChange={setBaseline} />
            <ExecutionPicker title="Target (e.g. failed)" imports={items} value={target} onChange={setTarget} />
          </div>
          <div className="flex justify-end">
            <Button type="submit" variant="primary" disabled={!baseline.import_id || !target.import_id} loading={compare.isPending}>
              Compare executions
            </Button>
          </div>
        </form>
      )}
      {compare.error && <ErrorState error={compare.error} />}
      {compare.data && <ComparisonResultView result={compare.data} />}
    </>
  );
}
