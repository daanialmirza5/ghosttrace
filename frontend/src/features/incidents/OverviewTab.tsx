import { Bot, FileCode2, Info, Sparkles } from "lucide-react";
import { useState } from "react";

import { EventChip } from "../../components/EventInspector";
import { Badge, Button, Card, ErrorState, EvidenceBadge, ScoreBar, UncertaintyBadge, cx } from "../../components/ui";
import { useExplanation, useHypotheses } from "../../hooks/queries";
import { formatTime, humanize } from "../../lib/format";
import type { Hypothesis, IncidentDetail } from "../../types/api";
import { useWorkspaceIncident } from "./IncidentWorkspace";

function Chips({ ids, limit = 8 }: { ids: string[]; limit?: number }) {
  const [all, setAll] = useState(false);
  const shown = all ? ids : ids.slice(0, limit);
  if (ids.length === 0) return <span className="text-xs text-slate-400">none</span>;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map((id) => (
        <EventChip key={id} id={id} />
      ))}
      {ids.length > limit && (
        <button type="button" className="text-[11px] text-accent-700 hover:underline" onClick={() => setAll(!all)}>
          {all ? "show fewer" : `+${ids.length - limit} more`}
        </button>
      )}
    </span>
  );
}

function HypothesisCard({ hypothesis, expanded }: { hypothesis: Hypothesis; expanded: boolean }) {
  const [open, setOpen] = useState(expanded);
  return (
    <article className={cx("card", hypothesis.rank === 1 && "ring-1 ring-accent-100")} aria-labelledby={`hyp-${hypothesis.rank}`}>
      <div className="flex flex-wrap items-start gap-4 p-4">
        <div className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-700">#{hypothesis.rank}</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={`hyp-${hypothesis.rank}`} className="text-base font-semibold text-slate-900">
              {hypothesis.service}
            </h3>
            {hypothesis.candidate_kind === "inferred" && (
              <Badge tone="blue" title="This service emits no events; it is visible only through calls made to it.">
                inferred dependency
              </Badge>
            )}
            <UncertaintyBadge value={hypothesis.uncertainty} />
          </div>
          <p className="mt-1 text-sm text-slate-600">Hypothesis: {hypothesis.statement}.</p>
          <div className="mt-2 max-w-sm">
            <ScoreBar value={hypothesis.score} label={hypothesis.score_label} />
            <p className="mt-0.5 text-[11px] text-slate-400">{hypothesis.score_label}</p>
          </div>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide evidence" : "Show evidence"}
        </Button>
      </div>
      <div className="border-t border-slate-100 bg-slate-50/60 px-4 py-3 text-sm">
        <span className="font-medium text-slate-700">Next step: </span>
        <span className="text-slate-700">{hypothesis.next_step}</span>
      </div>
      {open && (
        <div className="space-y-4 border-t border-slate-100 p-4">
          <div className="overflow-x-auto">
            <table className="table" aria-label={`Scoring signals for ${hypothesis.service}`}>
              <thead>
                <tr>
                  <th>Signal</th>
                  <th className="text-right">Weight</th>
                  <th className="text-right">Value</th>
                  <th className="text-right">Contribution</th>
                  <th>Explanation and evidence</th>
                </tr>
              </thead>
              <tbody>
                {hypothesis.signals.map((signal) => (
                  <tr key={signal.name} className={signal.value === 0 ? "text-slate-400" : undefined}>
                    <td className="font-medium whitespace-nowrap">{humanize(signal.name)}</td>
                    <td className="text-right font-mono text-xs">{signal.weight.toFixed(2)}</td>
                    <td className="text-right font-mono text-xs">{signal.value.toFixed(2)}</td>
                    <td className="text-right font-mono text-xs">{signal.contribution.toFixed(3)}</td>
                    <td>
                      <p className="text-xs">{signal.explanation}</p>
                      {signal.evidence_event_ids.length > 0 && <div className="mt-1"><Chips ids={signal.evidence_event_ids} limit={4} /></div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {hypothesis.contradictions.length > 0 && (
            <div>
              <p className="label mb-1">Contradictory evidence</p>
              <ul className="space-y-2">
                {hypothesis.contradictions.map((item) => (
                  <li key={item.name} className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
                    <span className="font-medium">−{item.penalty.toFixed(2)}</span> {item.explanation}
                    <div className="mt-1">
                      <Chips ids={item.evidence_event_ids} limit={4} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {hypothesis.missing_information.length > 0 && (
            <div>
              <p className="label mb-1">Missing information</p>
              <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-600">
                {hypothesis.missing_information.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <p className="label mb-1">
              Supporting events {hypothesis.onset && <span className="normal-case">· onset {formatTime(hypothesis.onset)} UTC</span>}
            </p>
            <Chips ids={hypothesis.supporting_event_ids} />
          </div>
        </div>
      )}
    </article>
  );
}

function ExplanationPanel({ incident }: { incident: IncidentDetail }) {
  const explanation = useExplanation(incident.id);
  const data = explanation.data;
  return (
    <Card
      title={<span className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-slate-400" aria-hidden /> Narrative explanation</span>}
      actions={
        <Button size="sm" onClick={() => explanation.mutate()} loading={explanation.isPending}>
          {data ? "Regenerate" : "Generate"}
        </Button>
      }
    >
      {!data && !explanation.error && (
        <p className="text-sm text-slate-500">
          Summarises the computed evidence. Uses the configured AI provider if one is enabled in the backend; otherwise a deterministic template. Either way it only cites events in this incident.
        </p>
      )}
      {explanation.error && <ErrorState error={explanation.error} />}
      {data && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={data.source === "ai" ? "accent" : "slate"}>
              {data.source === "ai" ? <Bot className="h-3 w-3" aria-hidden /> : <FileCode2 className="h-3 w-3" aria-hidden />}
              {data.label}
            </Badge>
            {data.model && <span className="text-xs text-slate-500">{data.provider} · {data.model}</span>}
          </div>
          <p className="text-sm leading-relaxed text-slate-800">{data.summary}</p>
          {data.investigation_steps.length > 0 && (
            <ol className="list-decimal space-y-2 pl-5 text-sm text-slate-700">
              {data.investigation_steps.map((step) => (
                <li key={step.step}>
                  {step.step}
                  {step.evidence_event_ids.length > 0 && <div className="mt-1"><Chips ids={step.evidence_event_ids} limit={4} /></div>}
                </li>
              ))}
            </ol>
          )}
          <p className="flex items-start gap-1.5 text-xs text-slate-500">
            <Info className="mt-0.5 h-3 w-3 flex-none" aria-hidden /> {data.disclosure}
            {data.fallback_reason && ` Fallback reason: ${data.fallback_reason}.`}
          </p>
        </div>
      )}
    </Card>
  );
}

export function OverviewTab() {
  const incident = useWorkspaceIncident();
  const method = useHypotheses(incident.id).data?.method;
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <div className="space-y-4">
        <div
          className={cx(
            "rounded-xl border p-4",
            incident.evidence_status === "sufficient" ? "border-emerald-200 bg-emerald-50/60" : incident.evidence_status === "ambiguous" ? "border-amber-200 bg-amber-50/60" : "border-red-200 bg-red-50/60",
          )}
        >
          <div className="mb-1 flex items-center gap-2">
            <EvidenceBadge status={incident.evidence_status} />
          </div>
          <p className="text-sm text-slate-800">{incident.evidence_summary}</p>
        </div>

        <h2 className="pt-2 text-sm font-semibold text-slate-800">Ranked root-cause hypotheses</h2>
        {incident.hypotheses.length === 0 ? (
          <p className="text-sm text-slate-500">No candidate received a positive heuristic score.</p>
        ) : (
          incident.hypotheses.map((hypothesis) => <HypothesisCard key={hypothesis.rank} hypothesis={hypothesis} expanded={hypothesis.rank === 1} />)
        )}
        {incident.excluded_candidates.length > 0 && (
          <p className="text-xs text-slate-500">
            Ruled out: {incident.excluded_candidates.map((item) => `${item.service} (${item.reason})`).join("; ")}.
          </p>
        )}
      </div>

      <div className="space-y-6">
        <ExplanationPanel incident={incident} />
        <Card title="Detected signals" padded={false}>
          <ul className="divide-y divide-slate-100">
            {incident.signals.map((signal) => (
              <li key={signal.id} className="px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <Badge tone={signal.basis === "observed" ? "slate" : "accent"} title={signal.basis === "observed" ? "Direct count or measurement over imported events" : "Conclusion drawn from several observations"}>
                    {signal.basis}
                  </Badge>
                  <span className="text-xs font-medium text-slate-700">{humanize(signal.type)}</span>
                  <span className="ml-auto font-mono text-[11px] text-slate-400">{formatTime(signal.start)}</span>
                </div>
                <p className="mt-1 text-xs text-slate-600">{signal.description}</p>
                {signal.evidence_event_ids[0] && (
                  <div className="mt-1">
                    <EventChip id={signal.evidence_event_ids[0]} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
        {(incident.missing_information.length > 0 || incident.data_quality.length > 0) && (
          <Card title="Missing evidence and data quality">
            <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
              {incident.missing_information.map((item) => (
                <li key={item}>{item}</li>
              ))}
              {incident.data_quality.map((item) => (
                <li key={item.id}>{item.description}</li>
              ))}
            </ul>
          </Card>
        )}
        {method && (
          <Card title="How hypotheses are scored">
            <p className="mb-3 text-xs text-slate-600">{method.description}</p>
            <table className="table">
              <tbody>
                {Object.entries(method.weights).map(([name, weight]) => (
                  <tr key={name}>
                    <td className="text-xs">{humanize(name)}</td>
                    <td className="text-right font-mono text-xs">{weight.toFixed(2)}</td>
                  </tr>
                ))}
                {Object.entries(method.penalties).map(([name, penalty]) => (
                  <tr key={name} className="text-amber-800">
                    <td className="text-xs">Penalty: {humanize(name)}</td>
                    <td className="text-right font-mono text-xs">−{penalty.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  );
}
