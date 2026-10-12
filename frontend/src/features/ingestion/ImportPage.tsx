import { Database, FileUp, Trash2 } from "lucide-react";
import { useId, useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { Badge, Button, Card, EmptyState, ErrorState, Field, Loading, PageHeader, cx } from "../../components/ui";
import { useDeleteImport, useDemoDatasets, useImportDemo, useImports, useUploadImport } from "../../hooks/queries";
import { formatBytes, formatDateTime, formatNumber, humanize } from "../../lib/format";
import type { ImportSummary } from "../../types/api";
import { ImportResult } from "./ImportResult";

export const CANONICAL_FIELDS = [
  "event_id",
  "timestamp",
  "service",
  "environment",
  "severity",
  "event_type",
  "message",
  "trace_id",
  "span_id",
  "parent_span_id",
  "request_id",
  "deployment_version",
  "duration_ms",
  "status_code",
  "target_service",
  "error_type",
] as const;

type Format = "auto" | "jsonl" | "json" | "csv";

/** Parse the header row of a CSV file (handles quoted names). */
export function parseCsvHeader(text: string): string[] {
  const line = text.split(/\r?\n/, 1)[0] ?? "";
  const columns: string[] = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"') {
      if (quoted && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else quoted = !quoted;
    } else if (char === "," && !quoted) {
      columns.push(current.trim());
      current = "";
    } else current += char;
  }
  if (current.trim() || columns.length) columns.push(current.trim());
  return columns.filter(Boolean);
}

function UploadCard({ onResult }: { onResult: (result: ImportSummary) => void }) {
  const upload = useUploadImport();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [format, setFormat] = useState<Format>("auto");
  const [columns, setColumns] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState(false);
  const ids = { file: useId(), name: useId(), format: useId() };
  const isCsv = format === "csv" || (format === "auto" && file?.name.toLowerCase().endsWith(".csv"));

  const choose = async (chosen: File | undefined) => {
    if (!chosen) return;
    setFile(chosen);
    setMapping({});
    upload.reset();
    if (chosen.name.toLowerCase().endsWith(".csv")) {
      const head = await chosen.slice(0, 64 * 1024).text();
      setColumns(parseCsvHeader(head));
    } else setColumns([]);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    void choose(event.dataTransfer.files[0]);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    const fieldMapping = Object.fromEntries(Object.entries(mapping).filter(([, target]) => target));
    upload.mutate(
      { file, options: { name: name || undefined, format, fieldMapping: isCsv ? fieldMapping : null } },
      { onSuccess: onResult },
    );
  };

  return (
    <Card title="Upload a file">
      <form onSubmit={submit} className="space-y-4">
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cx(
            "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors",
            dragging ? "border-accent-500 bg-accent-50" : "border-slate-300 bg-slate-50",
          )}
        >
          <FileUp className="h-6 w-6 text-slate-400" aria-hidden />
          <p className="text-sm text-slate-700">{file ? <strong>{file.name}</strong> : "Drag a file here, or"}</p>
          {file && <p className="text-xs text-slate-500">{formatBytes(file.size)}</p>}
          <label htmlFor={ids.file} className="cursor-pointer text-sm font-medium text-accent-700 hover:underline">
            {file ? "Choose a different file" : "browse for a file"}
          </label>
          <input
            ref={inputRef}
            id={ids.file}
            type="file"
            accept=".jsonl,.ndjson,.json,.csv,.log,.txt"
            className="sr-only"
            data-testid="file-input"
            onChange={(event) => void choose(event.target.files?.[0])}
          />
          <p className="text-xs text-slate-500">JSON Lines, JSON array or {"{events: [...]}"} envelope, or CSV. Content is parsed, never executed.</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Import name (optional)" htmlFor={ids.name}>
            <input id={ids.name} className="input" value={name} maxLength={200} onChange={(event) => setName(event.target.value)} placeholder={file?.name ?? "e.g. checkout outage"} />
          </Field>
          <Field label="Format" htmlFor={ids.format} hint="Auto-detect uses the file extension and content.">
            <select id={ids.format} className="input" value={format} onChange={(event) => setFormat(event.target.value as Format)}>
              <option value="auto">Auto-detect</option>
              <option value="jsonl">JSON Lines</option>
              <option value="json">JSON document</option>
              <option value="csv">CSV</option>
            </select>
          </Field>
        </div>

        {isCsv && columns.length > 0 && (
          <fieldset className="rounded-lg border border-slate-200 p-3">
            <legend className="px-1 text-sm font-medium text-slate-700">CSV field mapping</legend>
            <p className="mb-3 text-xs text-slate-500">
              Columns left on “auto” are matched against known field aliases; anything unrecognised is kept as an attribute.
            </p>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {columns.map((column) => (
                <label key={column} className="flex items-center gap-2 text-sm">
                  <span className="w-28 truncate font-mono text-xs" title={column}>
                    {column}
                  </span>
                  <select
                    aria-label={`Map column ${column}`}
                    className="input py-1"
                    value={mapping[column] ?? ""}
                    onChange={(event) => setMapping((current) => ({ ...current, [column]: event.target.value }))}
                  >
                    <option value="">auto</option>
                    {CANONICAL_FIELDS.map((fieldName) => (
                      <option key={fieldName} value={fieldName}>
                        {fieldName}
                      </option>
                    ))}
                    <option value={`attributes.${column}`}>attribute</option>
                  </select>
                </label>
              ))}
            </div>
          </fieldset>
        )}

        {upload.error && <ErrorState error={upload.error} />}
        <div className="flex justify-end">
          <Button type="submit" variant="primary" disabled={!file} loading={upload.isPending}>
            Validate and import
          </Button>
        </div>
      </form>
    </Card>
  );
}

function DemoDatasets({ onResult }: { onResult: (result: ImportSummary) => void }) {
  const { data, error, isLoading } = useDemoDatasets();
  const importDemo = useImportDemo();
  return (
    <Card title={<span className="flex items-center gap-2"><Database className="h-4 w-4 text-slate-400" aria-hidden /> Bundled synthetic datasets</span>} padded={false}>
      {isLoading && <Loading />}
      {error && <div className="p-4"><ErrorState error={error} /></div>}
      {data && data.length === 0 && <EmptyState title="No demo datasets found" description="Run scripts/generate_datasets.py to create them." />}
      <ul className="divide-y divide-slate-100">
        {data?.map((dataset) => (
          <li key={dataset.name} className="flex items-center justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-800">{dataset.title}</p>
              <p className="text-xs text-slate-500">{dataset.summary}</p>
              <p className="mt-0.5 text-[11px] text-slate-400">
                {dataset.filename} · {formatBytes(dataset.size_bytes)}
                {dataset.field_mapping && " · uses a field mapping"}
              </p>
            </div>
            <Button
              size="sm"
              loading={importDemo.isPending && importDemo.variables === dataset.name}
              disabled={importDemo.isPending}
              onClick={() => importDemo.mutate(dataset.name, { onSuccess: onResult })}
              aria-label={`Import ${dataset.title}`}
            >
              Import
            </Button>
          </li>
        ))}
      </ul>
      {importDemo.error && <div className="p-4"><ErrorState error={importDemo.error} /></div>}
    </Card>
  );
}

function ImportHistory() {
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading } = useImports({ limit: 10, offset });
  const remove = useDeleteImport();
  return (
    <Card title="Import history" padded={false}>
      {isLoading && <Loading />}
      {error && <div className="p-4"><ErrorState error={error} /></div>}
      {data && data.items.length === 0 && <EmptyState title="Nothing imported yet" />}
      {data && data.items.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th className="text-right">Accepted / rejected</th>
                  <th className="text-right">Incidents</th>
                  <th>Imported</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <p className="font-medium">{item.name}</p>
                      <p className="font-mono text-[11px] text-slate-400">{item.id}</p>
                    </td>
                    <td>
                      <Badge tone={item.status === "completed" ? "green" : item.status === "failed" ? "red" : "amber"}>{humanize(item.status)}</Badge>
                    </td>
                    <td className="text-right tabular-nums">
                      {formatNumber(item.accepted)} / {formatNumber(item.rejected)}
                    </td>
                    <td className="text-right">
                      {item.incident_count ? (
                        <Link className="text-accent-700 hover:underline" to={`/incidents?import_id=${item.id}`}>
                          {item.incident_count}
                        </Link>
                      ) : (
                        0
                      )}
                    </td>
                    <td className="text-xs text-slate-500">{formatDateTime(item.created_at)}</td>
                    <td className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Delete import ${item.name}`}
                        onClick={() => {
                          if (window.confirm(`Delete "${item.name}" and all of its events, incidents and reports?`)) remove.mutate(item.id);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between px-4 py-2 text-xs text-slate-500">
            <span>
              {offset + 1}–{Math.min(offset + data.items.length, data.total)} of {data.total}
            </span>
            <div className="flex gap-2">
              <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>
                Previous
              </Button>
              <Button size="sm" disabled={offset + 10 >= data.total} onClick={() => setOffset(offset + 10)}>
                Next
              </Button>
            </div>
          </div>
        </>
      )}
      {remove.error && <div className="p-4"><ErrorState error={remove.error} /></div>}
    </Card>
  );
}

export function ImportPage() {
  const [result, setResult] = useState<ImportSummary | null>(null);
  return (
    <>
      <PageHeader
        title="Import events"
        description="Upload application events. Each record is validated, normalised to the canonical schema and analysed; malformed records are rejected with line-level reasons and never turned into valid-looking events."
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-6">
          <UploadCard onResult={setResult} />
          {result && <ImportResult result={result} />}
        </div>
        <DemoDatasets onResult={setResult} />
      </div>
      <div className="mt-6">
        <ImportHistory />
      </div>
    </>
  );
}
