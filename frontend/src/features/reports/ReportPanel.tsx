import { Download, FileText } from "lucide-react";
import { useId, useState } from "react";

import { Button, Card, ErrorState, Field, Loading } from "../../components/ui";
import { useComparisons, useCreateReport, useReports } from "../../hooks/queries";
import { api } from "../../services/api";
import { formatBytes, formatDateTime } from "../../lib/format";
import type { IncidentDetail, Report } from "../../types/api";

function Preview({ report }: { report: Report }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500">
          {report.filename} · {formatBytes(report.size_bytes)} · {report.referenced_event_count} event IDs verified against the import · SHA-256 <code>{report.sha256.slice(0, 12)}…</code>
        </p>
        <a
          href={api.reportDownloadUrl(report)}
          download={report.filename}
          className="inline-flex items-center gap-2 rounded-lg bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700"
        >
          <Download className="h-4 w-4" aria-hidden /> Download {report.format === "json" ? "JSON" : "Markdown"}
        </a>
      </div>
      <pre className="max-h-[32rem] overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs leading-relaxed whitespace-pre-wrap" data-testid="report-preview">
        {report.content}
      </pre>
    </div>
  );
}

export function ReportPanel({ incident }: { incident: IncidentDetail }) {
  const [format, setFormat] = useState<"markdown" | "json">("markdown");
  const [comparisonId, setComparisonId] = useState("");
  const create = useCreateReport(incident.id);
  const reports = useReports(incident.id);
  const comparisons = useComparisons();
  const ids = { format: useId(), comparison: useId() };
  const relevant = (comparisons.data?.items ?? []).filter(
    (item) => item.baseline_ref.import_id === incident.import_id || item.target_ref.import_id === incident.import_id,
  );

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <Card title={<span className="flex items-center gap-2"><FileText className="h-4 w-4 text-slate-400" aria-hidden /> Generate incident report</span>}>
        <form
          className="mb-4 flex flex-wrap items-end gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ format, comparisonId: comparisonId || null });
          }}
        >
          <Field label="Format" htmlFor={ids.format}>
            <select id={ids.format} className="input w-40" value={format} onChange={(e) => setFormat(e.target.value as "markdown" | "json")}>
              <option value="markdown">Markdown</option>
              <option value="json">JSON</option>
            </select>
          </Field>
          <Field label="Include comparison (optional)" htmlFor={ids.comparison} hint={relevant.length === 0 ? "Run a comparison involving this import to include it." : undefined}>
            <select id={ids.comparison} className="input w-72" value={comparisonId} onChange={(e) => setComparisonId(e.target.value)} disabled={relevant.length === 0}>
              <option value="">None</option>
              {relevant.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.baseline.label} vs {item.target.label} ({formatDateTime(item.created_at)})
                </option>
              ))}
            </select>
          </Field>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Generate report
          </Button>
        </form>
        {create.error && <ErrorState error={create.error} />}
        {create.data ? (
          <Preview report={create.data} />
        ) : (
          <p className="text-sm text-slate-500">
            Reports include the summary, timeline, impacted services, ranked hypotheses with their scoring signals, supporting and missing evidence, recommended investigations and
            (optionally) comparison results. Every cited event ID is verified to exist before the report is produced.
          </p>
        )}
      </Card>
      <Card title="Previous reports" padded={false}>
        {reports.isLoading && <Loading />}
        {reports.error && <div className="p-4"><ErrorState error={reports.error} /></div>}
        {reports.data?.length === 0 && <p className="p-4 text-sm text-slate-500">No reports generated yet.</p>}
        <ul className="divide-y divide-slate-100">
          {reports.data?.map((report) => (
            <li key={report.id} className="flex items-center justify-between gap-2 px-4 py-2 text-sm">
              <span className="min-w-0">
                <span className="block truncate">{report.filename}</span>
                <span className="text-xs text-slate-500">
                  {formatDateTime(report.created_at)} · {formatBytes(report.size_bytes)}
                </span>
              </span>
              <a className="text-xs font-medium text-accent-700 hover:underline" href={api.reportDownloadUrl(report)} download={report.filename}>
                Download
              </a>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
