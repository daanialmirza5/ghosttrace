import { Link } from "react-router-dom";

import { Card, PageHeader } from "../components/ui";

const FIELDS: [string, string, string][] = [
  ["event_id", "id, uuid, log_id", "Derived from a content hash if missing"],
  ["timestamp", "ts, time, @timestamp", "Required. ISO 8601 or Unix seconds/ms/µs; naive times are assumed UTC (warning)"],
  ["service", "service_name, app, component", "Required"],
  ["severity", "level, log_level, lvl", "Required. debug, info, warning, error, critical (+ aliases such as warn, fatal)"],
  ["event_type", "type, kind, category", "log (default), request, span, dependency_call, exception, timeout, retry, deployment, config_change, metric, healthcheck"],
  ["message", "msg, log, text, body", "Free text, treated as untrusted data"],
  ["trace_id / span_id / parent_span_id", "traceId, spanId, parent_id", "Enable trace-ancestry correlation"],
  ["request_id", "correlation_id", "Groups events without traces"],
  ["target_service", "peer.service, downstream, dependency", "Records an outbound call (creates a dependency edge)"],
  ["duration_ms / status_code / error_type", "latency_ms, http_status, exception_type", "Latency, HTTP status and error classification"],
  ["deployment_version", "version, release, build", "Enables implicit version-change detection"],
];

export function HelpPage() {
  return (
    <>
      <PageHeader title="Help and documentation" description="How GhostTrace reconstructs incidents, what it can and cannot conclude, and the event format it accepts." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Workflow">
          <ol className="list-decimal space-y-2 pl-5 text-sm text-slate-700">
            <li><Link className="text-accent-700 hover:underline" to="/import">Import</Link> a JSONL, JSON or CSV file, or a bundled synthetic dataset.</li>
            <li>GhostTrace validates every record, correlates events by trace, span, request ID and recorded dependency calls, and detects anomalous signals.</li>
            <li>Overlapping signals form an <Link className="text-accent-700 hover:underline" to="/incidents">incident</Link>. Each candidate service gets a heuristic score from six documented signals minus penalties for contradictory evidence.</li>
            <li>Review hypotheses, open any event ID to see the raw evidence, explore the timeline and service graph, and replay the incident event by event.</li>
            <li><Link className="text-accent-700 hover:underline" to="/compare">Compare</Link> against a healthy execution and export a verified <Link className="text-accent-700 hover:underline" to="/reports">report</Link>.</li>
          </ol>
        </Card>
        <Card title="What the scores mean">
          <ul className="list-disc space-y-2 pl-5 text-sm text-slate-700">
            <li>Scores are <strong>uncalibrated heuristics</strong> that order candidates within one incident. They are not probabilities.</li>
            <li>A top-ranked hypothesis is supported by correlation in the imported data; it is not proof of causation.</li>
            <li>Timing alone never creates a dependency edge or a causal link. It contributes only as one weighted signal (temporal precedence).</li>
            <li>When affected services are not linked by traces, dependency calls or change events, GhostTrace reports <em>insufficient evidence</em> instead of guessing.</li>
            <li>Signals are labelled <em>observed</em> (direct counts) or <em>inferred</em> (conclusions from several observations, such as a deployment regression or cascade).</li>
          </ul>
        </Card>
        <Card title="Canonical event fields" className="lg:col-span-2" padded={false}>
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Accepted aliases (case-insensitive)</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {FIELDS.map(([field, aliases, notes]) => (
                  <tr key={field}>
                    <td className="font-mono text-xs">{field}</td>
                    <td className="font-mono text-xs text-slate-600">{aliases}</td>
                    <td className="text-xs text-slate-600">{notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="p-4 text-xs text-slate-500">
            Unknown fields are kept as attributes. Records with unparseable values or conflicting aliases are rejected with their line number. Conflicting duplicates of an event ID are
            rejected; exact duplicates are skipped. See docs/event-format.md in the repository for examples.
          </p>
        </Card>
        <Card title="Keyboard shortcuts">
          <ul className="space-y-1 text-sm">
            <li><kbd className="rounded border px-1">Space</kbd> play / pause replay</li>
            <li><kbd className="rounded border px-1">←</kbd> <kbd className="rounded border px-1">→</kbd> step one frame (hold Shift for 10)</li>
            <li><kbd className="rounded border px-1">Home</kbd> <kbd className="rounded border px-1">End</kbd> jump to first / last frame</li>
            <li><kbd className="rounded border px-1">Esc</kbd> close the event drawer</li>
          </ul>
        </Card>
        <Card title="Privacy and limits">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
            <li>Uploaded files are parsed in memory; only normalised events are stored, and imports expire after the configured retention period.</li>
            <li>The optional AI layer is off by default. When enabled, raw log messages are sent only if explicitly configured.</li>
            <li>Rate and size limits apply to uploads; see Settings for current values.</li>
          </ul>
        </Card>
      </div>
    </>
  );
}
