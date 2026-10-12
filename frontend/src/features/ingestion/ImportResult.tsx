import { CheckCircle2, CircleAlert, XCircle } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, Card } from "../../components/ui";
import { formatBytes, formatDateTime, formatNumber, humanize } from "../../lib/format";
import type { ImportSummary } from "../../types/api";

export function ImportResult({ result }: { result: ImportSummary }) {
  const Icon = result.status === "completed" ? CheckCircle2 : result.status === "failed" ? XCircle : CircleAlert;
  const tone = result.status === "completed" ? "text-emerald-600" : result.status === "failed" ? "text-red-600" : "text-amber-600";
  return (
    <Card title={<span className="flex items-center gap-2"><Icon className={`h-4 w-4 ${tone}`} aria-hidden /> Import summary: {result.name}</span>}>
      <div aria-live="polite" className="space-y-4">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {[
            ["Status", <Badge key="s" tone={result.status === "completed" ? "green" : result.status === "failed" ? "red" : "amber"}>{humanize(result.status)}</Badge>],
            ["Records read", formatNumber(result.total_records)],
            ["Accepted", formatNumber(result.accepted)],
            ["Rejected", formatNumber(result.rejected)],
            ["Duplicates skipped", formatNumber(result.duplicates)],
          ].map(([label, value]) => (
            <div key={String(label)}>
              <dt className="label">{label}</dt>
              <dd className="mt-1 font-medium tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-slate-500">
          {result.format?.toUpperCase() ?? "Unknown format"} · {formatBytes(result.size_bytes)} · SHA-256 <code>{result.content_sha256.slice(0, 16)}…</code>
          {result.first_event_at && ` · events from ${formatDateTime(result.first_event_at)} to ${formatDateTime(result.last_event_at)}`}
        </p>

        {result.file_error && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            The file could not be imported: {result.file_error}
          </p>
        )}

        {Object.keys(result.warnings).length > 0 && (
          <div>
            <p className="label mb-1">Warnings</p>
            <ul className="flex flex-wrap gap-2">
              {Object.entries(result.warnings).map(([key, count]) => (
                <li key={key}>
                  <Badge tone="amber">
                    {humanize(key)}: {count}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}

        {result.errors.length > 0 && (
          <div>
            <p className="label mb-1">
              Rejected records {result.errors_truncated && <span className="normal-case">(first {result.errors.length} shown)</span>}
            </p>
            <div className="max-h-64 overflow-auto rounded-lg border border-slate-200">
              <table className="table" aria-label="Validation errors">
                <thead>
                  <tr>
                    <th>Position</th>
                    <th>Field</th>
                    <th>Problem</th>
                  </tr>
                </thead>
                <tbody>
                  {result.errors.map((error) => (
                    <tr key={`${error.kind}-${error.position}-${error.message}`}>
                      <td className="font-mono text-xs whitespace-nowrap">
                        {error.kind} {error.position}
                      </td>
                      <td className="text-xs">{error.field ?? "—"}</td>
                      <td className="text-xs text-slate-700">{error.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {result.status !== "failed" && (
          <p className="text-sm">
            Analysis {result.analysis_status}
            {result.analysis_ms !== null && ` in ${result.analysis_ms.toFixed(0)} ms`}:{" "}
            {result.incident_count === 0 ? (
              <span className="text-slate-600">no incidents detected.</span>
            ) : (
              <Link to={`/incidents?import_id=${result.id}`} className="font-medium text-accent-700 hover:underline">
                {result.incident_count} incident{result.incident_count === 1 ? "" : "s"} detected →
              </Link>
            )}
            {result.analysis_error && <span className="text-red-700"> ({result.analysis_error})</span>}
          </p>
        )}
      </div>
    </Card>
  );
}
