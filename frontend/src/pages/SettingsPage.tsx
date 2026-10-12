import { CheckCircle2, XCircle } from "lucide-react";

import { Badge, Button, Card, ErrorState, Loading, PageHeader } from "../components/ui";
import { useReadiness, useSettings } from "../hooks/queries";
import { API_BASE } from "../services/api";
import { formatBytes } from "../lib/format";

const ENV_VARS: [string, string][] = [
  ["GHOSTTRACE_DATABASE_URL", "SQLite by default; postgresql+psycopg://… for PostgreSQL"],
  ["GHOSTTRACE_CORS_ORIGINS", "Comma-separated browser origins allowed to call the API"],
  ["GHOSTTRACE_MAX_UPLOAD_BYTES", "Upload size limit"],
  ["GHOSTTRACE_MAX_RECORDS_PER_IMPORT", "Record limit per import"],
  ["GHOSTTRACE_RETENTION_HOURS", "Delete imports older than this (0 disables)"],
  ["GHOSTTRACE_RATE_LIMIT_PER_MINUTE", "Mutating requests per client per minute (0 disables)"],
  ["GHOSTTRACE_AI_PROVIDER", "none (default) or anthropic"],
  ["GHOSTTRACE_AI_SEND_EVENT_MESSAGES", "Send raw log messages to the AI provider (default false)"],
];

export function SettingsPage() {
  const settings = useSettings();
  const ready = useReadiness();
  return (
    <>
      <PageHeader title="Settings and local configuration" description="Effective backend configuration, read live from the API. Configuration is changed with environment variables or backend/.env; secrets are never shown." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Backend readiness" actions={<Button size="sm" onClick={() => void ready.refetch()} loading={ready.isFetching}>Recheck</Button>}>
          {ready.isLoading && <Loading />}
          {ready.error && <ErrorState error={ready.error} />}
          {ready.data && (
            <ul className="space-y-2">
              {ready.data.checks.map((check) => (
                <li key={check.name} className="flex items-center gap-2 text-sm">
                  {check.ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden /> : <XCircle className="h-4 w-4 text-red-600" aria-hidden />}
                  <span className="font-medium capitalize">{check.name}</span>
                  <span className="text-slate-500">{check.detail}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-slate-500">
            API base: <code>{API_BASE || window.location.origin}</code>/api/v1 · <a className="text-accent-700 hover:underline" href={`${API_BASE}/docs`} target="_blank" rel="noreferrer">OpenAPI docs</a>
          </p>
        </Card>
        <Card title="Effective configuration">
          {settings.isLoading && <Loading />}
          {settings.error && <ErrorState error={settings.error} />}
          {settings.data && (
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <dt className="text-slate-500">Version</dt>
              <dd>{settings.data.version}</dd>
              <dt className="text-slate-500">Environment</dt>
              <dd>{settings.data.environment}</dd>
              <dt className="text-slate-500">Database</dt>
              <dd>{settings.data.database_backend}</dd>
              <dt className="text-slate-500">Upload limit</dt>
              <dd>{formatBytes(settings.data.max_upload_bytes)}</dd>
              <dt className="text-slate-500">Records per import</dt>
              <dd>{settings.data.max_records_per_import.toLocaleString()}</dd>
              <dt className="text-slate-500">Retention</dt>
              <dd>{settings.data.retention_hours === 0 ? "disabled" : `${settings.data.retention_hours} h`}</dd>
              <dt className="text-slate-500">Rate limit</dt>
              <dd>{settings.data.rate_limit_per_minute === 0 ? "disabled" : `${settings.data.rate_limit_per_minute} mutating requests/min`}</dd>
              <dt className="text-slate-500">AI explanations</dt>
              <dd>
                {settings.data.ai_enabled ? <Badge tone="accent">{settings.data.ai_provider} · {settings.data.ai_model}</Badge> : <Badge>disabled (deterministic)</Badge>}
              </dd>
              <dt className="text-slate-500">Raw messages to AI</dt>
              <dd>{settings.data.ai_send_event_messages ? <Badge tone="amber">sent</Badge> : "never sent"}</dd>
              <dt className="text-slate-500">CORS origins</dt>
              <dd className="text-xs break-all">{settings.data.cors_origins.join(", ")}</dd>
            </dl>
          )}
        </Card>
        <Card title="Environment variables" className="lg:col-span-2" padded={false}>
          <table className="table">
            <tbody>
              {ENV_VARS.map(([name, description]) => (
                <tr key={name}>
                  <td className="font-mono text-xs">{name}</td>
                  <td className="text-sm text-slate-600">{description}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="p-4 text-xs text-slate-500">The full list with defaults is in .env.example at the repository root.</p>
        </Card>
      </div>
    </>
  );
}
