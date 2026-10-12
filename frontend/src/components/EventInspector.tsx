import { X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useIncidentEvent } from "../hooks/queries";
import { formatMs, formatTime } from "../lib/format";
import type { EventRecord } from "../types/api";
import { Badge, Button, ErrorState, Loading, SeverityBadge, cx } from "./ui";

interface InspectorContextValue {
  incidentId: string | null;
  openEvent: (eventId: string) => void;
}

const InspectorContext = createContext<InspectorContextValue>({ incidentId: null, openEvent: () => undefined });

export const useEventInspector = () => useContext(InspectorContext);

/** Clickable event ID. Opens the evidence drawer when inside an incident. */
export function EventChip({ id, className }: { id: string; className?: string }) {
  const { openEvent, incidentId } = useEventInspector();
  if (!incidentId) return <code className={cx("text-xs", className)}>{id}</code>;
  return (
    <button
      type="button"
      onClick={() => openEvent(id)}
      className={cx("rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700 hover:bg-accent-100 hover:text-accent-700", className)}
      title="Inspect event"
    >
      {id}
    </button>
  );
}

function FieldRow({ name, value }: { name: string; value: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-2 py-1 text-sm">
      <dt className="text-slate-500">{name}</dt>
      <dd className="min-w-0 break-words text-slate-900">{value}</dd>
    </div>
  );
}

function EventFields({ event }: { event: EventRecord }) {
  return (
    <dl className="divide-y divide-slate-100">
      <FieldRow name="Event ID" value={<code className="text-xs">{event.event_id}</code>} />
      <FieldRow name="Timestamp" value={`${formatTime(event.timestamp, true)} UTC`} />
      <FieldRow name="Service" value={event.service} />
      <FieldRow name="Severity" value={<SeverityBadge severity={event.severity} />} />
      <FieldRow name="Type" value={event.event_type} />
      <FieldRow name="Target service" value={event.target_service} />
      <FieldRow name="Duration" value={event.duration_ms !== null ? formatMs(event.duration_ms) : null} />
      <FieldRow name="Status code" value={event.status_code} />
      <FieldRow name="Error type" value={event.error_type} />
      <FieldRow name="Version" value={event.deployment_version} />
      <FieldRow name="Environment" value={event.environment} />
      <FieldRow name="Trace ID" value={event.trace_id && <code className="text-xs">{event.trace_id}</code>} />
      <FieldRow name="Span / parent" value={event.span_id && <code className="text-xs">{event.span_id} ← {event.parent_span_id ?? "root"}</code>} />
      <FieldRow name="Request ID" value={event.request_id} />
      {Object.entries(event.attributes).map(([key, value]) => (
        <FieldRow key={key} name={key} value={String(value)} />
      ))}
      {event.event_id_derived && <FieldRow name="ID provenance" value="derived from record content (source had no ID)" />}
    </dl>
  );
}

function Drawer({ incidentId, eventId, onClose, onOpen }: { incidentId: string; eventId: string; onClose: () => void; onOpen: (id: string) => void }) {
  const { data, error, isLoading, refetch } = useIncidentEvent(incidentId, eventId);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/20" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`Event ${eventId}`}
        className="h-full w-full max-w-xl overflow-y-auto border-l border-slate-200 bg-white shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="sticky top-0 flex items-center justify-between border-b border-slate-100 bg-white px-5 py-3">
          <h2 className="text-sm font-semibold">Event evidence</h2>
          <Button ref={closeRef} variant="ghost" size="sm" onClick={onClose} aria-label="Close event details">
            <X className="h-4 w-4" />
          </Button>
        </header>
        <div className="space-y-5 p-5">
          {isLoading && <Loading />}
          {error && <ErrorState error={error} onRetry={() => void refetch()} />}
          {data && (
            <>
              <section>
                <p className="mb-2 rounded-lg bg-slate-50 p-3 font-mono text-xs break-words whitespace-pre-wrap text-slate-800">{data.event.message || "(no message)"}</p>
                <EventFields event={data.event} />
              </section>
              <section>
                <h3 className="label mb-2">Cited by</h3>
                {data.referenced_by.length === 0 ? (
                  <p className="text-sm text-slate-500">Not cited by any signal or hypothesis.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {data.referenced_by.map((ref) => (
                      <li key={`${ref.kind}-${ref.ref}-${ref.label}`} className="flex items-start gap-2 text-sm">
                        <Badge tone={ref.kind === "hypothesis" ? "accent" : "slate"}>{ref.kind}</Badge>
                        <span className="text-slate-700">{ref.label}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section>
                <h3 className="label mb-2">
                  Related events {data.relation !== "none" && <span className="normal-case">(same {data.relation})</span>}
                </h3>
                {data.related_events.length === 0 ? (
                  <p className="text-sm text-slate-500">No events share this event's trace or request ID.</p>
                ) : (
                  <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
                    {data.related_events.map((related) => (
                      <li key={related.event_id}>
                        <button type="button" className="flex w-full items-start gap-2 px-3 py-2 text-left text-xs hover:bg-slate-50" onClick={() => onOpen(related.event_id)}>
                          <span className="w-24 flex-none font-mono text-slate-500">{formatTime(related.timestamp)}</span>
                          <span className="w-32 flex-none truncate font-medium text-slate-700">{related.service}</span>
                          <SeverityBadge severity={related.severity} />
                          <span className="truncate text-slate-600">{related.message}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

export function EventInspectorProvider({ incidentId, children }: { incidentId: string; children: ReactNode }) {
  const [eventId, setEventId] = useState<string | null>(null);
  const openEvent = useCallback((id: string) => setEventId(id), []);
  const close = useCallback(() => setEventId(null), []);
  const value = useMemo(() => ({ incidentId, openEvent }), [incidentId, openEvent]);
  return (
    <InspectorContext.Provider value={value}>
      {children}
      {eventId && <Drawer incidentId={incidentId} eventId={eventId} onClose={close} onOpen={openEvent} />}
    </InspectorContext.Provider>
  );
}
