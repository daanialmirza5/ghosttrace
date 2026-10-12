"""Incident report generation (JSON and Markdown).

Every event ID cited anywhere in a report is checked against the import before the report
is returned; a report that would cite a missing event is refused. Imported text (messages,
error types) is untrusted and is escaped when rendered to Markdown so it cannot inject
links, images, HTML or table breaks.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app import __version__
from app.core.timeutil import iso
from app.models.comparisons import ComparisonRecord
from app.models.incidents import IncidentRecord
from app.repositories import imports as import_repo
from app.schemas.events import CanonicalEvent, EventType
from app.services.correlation import correlate
from app.services.graph_analysis import build_graph
from app.services.incidents import referenced_event_ids, window_events

DISCLAIMER = (
    "Hypotheses are ranked by an uncalibrated heuristic score in [0, 1]. The score orders "
    "candidates within this incident and is not a probability. A ranked hypothesis is "
    "supported by correlation in the imported events; it is not proof of causation."
)
MAX_EVIDENCE_ROWS = 60
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+!|~])")


class ReportIntegrityError(RuntimeError):
    """The report referenced event IDs that do not exist in the import."""


def md_escape(text: object, limit: int = 300) -> str:
    value = re.sub(r"\s+", " ", str(text)).strip()
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    return _MD_SPECIAL.sub(r"\\\1", value)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _narrative(incident: IncidentRecord) -> str:
    hypotheses = incident.hypotheses
    if incident.evidence_status == "insufficient" or not hypotheses:
        return (
            f"GhostTrace detected {incident.title.lower()} between "
            f"{incident.detected_start:%H:%M:%S} and {incident.detected_end:%H:%M:%S} UTC but "
            "could not rank a root cause with the available evidence. "
            + " ".join(f"Missing: {item}." for item in incident.missing_information[:3])
        )
    top = hypotheses[0]
    strongest = sorted(top["signals"], key=lambda s: -s["contribution"])[:3]
    reasons = "; ".join(s["explanation"] for s in strongest if s["value"] > 0)
    text = (
        f"GhostTrace detected {incident.title.lower()} between "
        f"{incident.detected_start:%H:%M:%S} and {incident.detected_end:%H:%M:%S} UTC. "
        f"The highest-ranked hypothesis is that it originated in {top['service']} "
        f"(heuristic score {top['score']:.2f}, {top['uncertainty']} uncertainty): {reasons}."
    )
    if top["contradictions"]:
        text += (
            " Contradicting evidence: "
            + "; ".join(c["explanation"] for c in top["contradictions"])
            + "."
        )
    if len(hypotheses) > 1:
        runner = hypotheses[1]
        text += f" The next candidate is {runner['service']} (score {runner['score']:.2f})."
    return text


def _timeline(incident: IncidentRecord, events: list[CanonicalEvent]) -> list[dict[str, Any]]:
    by_id = {event.event_id: event for event in events}
    entries: list[dict[str, Any]] = []
    for event in events:
        if event.event_type in (EventType.DEPLOYMENT, EventType.CONFIG_CHANGE):
            entries.append(
                {
                    "timestamp": iso(event.timestamp),
                    "event_id": event.event_id,
                    "service": event.service,
                    "kind": "change",
                    "description": event.message,
                }
            )
    first_error: dict[str, CanonicalEvent] = {}
    for event in events:
        if event.is_error and event.service not in first_error:
            first_error[event.service] = event
    for service, event in first_error.items():
        entries.append(
            {
                "timestamp": iso(event.timestamp),
                "event_id": event.event_id,
                "service": service,
                "kind": "first_error",
                "description": event.message,
            }
        )
    for signal in incident.signals:
        evidence = [eid for eid in signal["evidence_event_ids"] if eid in by_id]
        entries.append(
            {
                "timestamp": signal["start"].replace("+00:00", "Z"),
                "event_id": evidence[0] if evidence else None,
                "service": signal["service"],
                "kind": f"signal:{signal['type']}",
                "description": signal["description"],
            }
        )
    entries.sort(key=lambda entry: (_parse(entry["timestamp"]), entry["kind"]))
    return entries[:80]


def build_report_data(
    session: Session,
    incident: IncidentRecord,
    *,
    comparison: ComparisonRecord | None = None,
    generated_at: datetime,
) -> dict[str, Any]:
    source = import_repo.get_import(session, incident.import_id)
    events = window_events(session, incident)
    graph = build_graph(events, correlate(events))

    cited: dict[str, list[str]] = {}

    def cite(event_ids: Iterable[str], by: str) -> None:
        for event_id in event_ids:
            if event_id:
                cited.setdefault(event_id, [])
                if by not in cited[event_id]:
                    cited[event_id].append(by)

    for signal in incident.signals:
        cite(signal["evidence_event_ids"][:5], f"signal {signal['id']}")
    for hypothesis in incident.hypotheses:
        label = f"hypothesis #{hypothesis['rank']}"
        if hypothesis.get("key_event_id"):
            cite([hypothesis["key_event_id"]], label)
        cite(hypothesis["supporting_event_ids"][:10], label)
    timeline = _timeline(incident, events)
    cite((entry["event_id"] for entry in timeline if entry["event_id"]), "timeline")

    all_referenced = set(cited) | referenced_event_ids(incident)
    found = import_repo.existing_event_ids(session, incident.import_id, all_referenced)
    missing = all_referenced - found
    if missing:
        raise ReportIntegrityError(
            f"report would cite {len(missing)} event IDs that are not in the import"
        )

    by_id = {event.event_id: event for event in events}
    evidence_rows: list[dict[str, Any]] = []
    for event_id, citations in cited.items():
        event = by_id.get(event_id)
        if event is None:
            row = import_repo.get_event(session, incident.import_id, event_id)
            event = import_repo.to_canonical(row)
        evidence_rows.append(
            {
                "event_id": event.event_id,
                "timestamp": iso(event.timestamp),
                "service": event.service,
                "severity": event.severity.value,
                "event_type": event.event_type.value,
                "message": event.message[:500],
                "cited_by": citations,
            }
        )
    evidence_rows.sort(key=lambda row: (_parse(row["timestamp"]), row["event_id"]))

    impacted = [
        {
            "service": node.name,
            "kind": node.kind,
            "status": node.status,
            "event_count": node.event_count,
            "error_count": node.error_count,
            "error_rate": None if node.error_rate is None else round(node.error_rate, 4),
            "p95_ms": node.p95_ms,
        }
        for node in sorted(graph.nodes.values(), key=lambda n: (-n.error_count, n.name))
        if node.status in ("failing", "degraded") or node.name in incident.services
    ]

    comparison_block = None
    if comparison is not None:
        result = comparison.result
        comparison_block = {
            "comparison_id": comparison.id,
            "comparable": result["comparable"],
            "incomparable_reasons": result["incomparable_reasons"],
            "warnings": result["warnings"],
            "baseline": result["baseline"],
            "target": result["target"],
            "overall": result["overall"],
            "findings": result["findings"][:10],
        }

    return {
        "report_version": "1.0",
        "generator": f"GhostTrace {__version__}",
        "generated_at": iso(generated_at),
        "disclaimer": DISCLAIMER,
        "source": {
            "import_id": source.id,
            "import_name": source.name,
            "filename": source.source_filename,
            "content_sha256": source.content_sha256,
            "accepted_records": source.accepted_count,
            "rejected_records": source.rejected_count,
        },
        "incident": {
            "id": incident.id,
            "title": incident.title,
            "severity": incident.severity,
            "evidence_status": incident.evidence_status,
            "evidence_summary": incident.evidence_summary,
            "detected_start": iso(incident.detected_start),
            "detected_end": iso(incident.detected_end),
            "window_start": iso(incident.window_start),
            "window_end": iso(incident.window_end),
            "error_count": incident.error_count,
            "event_count": incident.event_count,
            "services": incident.services,
        },
        "narrative": {"source": "deterministic_template", "text": _narrative(incident)},
        "impacted_services": impacted,
        "timeline": timeline,
        "hypotheses": incident.hypotheses,
        "excluded_candidates": incident.excluded_candidates,
        "evidence": evidence_rows[:MAX_EVIDENCE_ROWS],
        "missing_evidence": incident.missing_information,
        "data_quality": [item["description"] for item in source.data_quality or []],
        "recommended_investigations": [
            {"rank": h["rank"], "service": h["service"], "step": h["next_step"]}
            for h in incident.hypotheses[:3]
        ],
        "comparison": comparison_block,
        "event_id_check": {"referenced": len(all_referenced), "verified": len(found)},
    }


def render_markdown(data: dict[str, Any]) -> str:
    incident = data["incident"]
    lines: list[str] = [
        f"# Incident report: {md_escape(incident['title'])}",
        "",
        f"*Generated {data['generated_at']} by {data['generator']} from import "
        f"`{data['source']['import_id']}` (SHA-256 `{data['source']['content_sha256'][:16]}…`).*",
        "",
        f"> {md_escape(data['disclaimer'], 1000)}",
        "",
        "## Summary",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Incident | `{incident['id']}` |",
        f"| Severity | {incident['severity']} |",
        f"| Evidence status | **{incident['evidence_status']}** |",
        f"| Detected | {incident['detected_start']} to {incident['detected_end']} |",
        f"| Error events in window | {incident['error_count']} of {incident['event_count']} |",
        f"| Services | {md_escape(', '.join(incident['services']))} |",
        "",
        md_escape(incident["evidence_summary"], 1000),
        "",
        f"**Narrative ({data['narrative']['source'].replace('_', ' ')}).** "
        + md_escape(data["narrative"]["text"], 2000),
        "",
        "## Impacted services",
        "",
        "| Service | Kind | Status | Errors | Events | Error rate | p95 latency |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in data["impacted_services"]:
        rate = "n/a" if row["error_rate"] is None else f"{row['error_rate']:.1%}"
        p95 = "not measured" if row["p95_ms"] is None else f"{row['p95_ms']:.0f} ms"
        lines.append(
            f"| {md_escape(row['service'])} | {row['kind']} | {row['status']} | "
            f"{row['error_count']} | {row['event_count']} | {rate} | {p95} |"
        )

    lines += ["", "## Root-cause hypotheses", ""]
    if not data["hypotheses"]:
        lines.append("No candidate received a positive heuristic score.")
    for h in data["hypotheses"]:
        lines += [
            f"### #{h['rank']} {md_escape(h['service'])} — heuristic score {h['score']:.2f} "
            f"({h['uncertainty']} uncertainty)",
            "",
            md_escape(h["statement"]),
            "",
            "| Signal | Weight | Value | Contribution | Explanation |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
        for s in h["signals"]:
            lines.append(
                f"| {s['name']} | {s['weight']:.2f} | {s['value']:.2f} | "
                f"{s['contribution']:.3f} | {md_escape(s['explanation'])} |"
            )
        if h["contradictions"]:
            lines += ["", "**Contradictory evidence**", ""]
            lines += [
                f"- {md_escape(c['explanation'])} (penalty {c['penalty']:.2f})"
                for c in h["contradictions"]
            ]
        if h["missing_information"]:
            lines += ["", "**Missing information**", ""]
            lines += [f"- {md_escape(item)}" for item in h["missing_information"]]
        ids = ", ".join(f"`{eid}`" for eid in h["supporting_event_ids"][:12])
        lines += [
            "",
            f"Supporting events: {ids or 'none'}",
            "",
            f"**Next step:** {md_escape(h['next_step'], 600)}",
            "",
        ]

    if data["excluded_candidates"]:
        lines += [
            "Ruled out (score 0): "
            + ", ".join(
                f"{md_escape(c['service'])} ({md_escape(c['reason'])})"
                for c in data["excluded_candidates"]
            ),
            "",
        ]

    lines += [
        "## Timeline",
        "",
        "| Time (UTC) | Service | Kind | Description | Event |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in data["timeline"]:
        event = f"`{entry['event_id']}`" if entry["event_id"] else ""
        lines.append(
            f"| {entry['timestamp']} | {md_escape(entry['service'])} | {entry['kind']} | "
            f"{md_escape(entry['description'], 160)} | {event} |"
        )

    lines += [
        "",
        "## Supporting evidence",
        "",
        "| Event | Time (UTC) | Service | Severity | Type | Message | Cited by |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["evidence"]:
        lines.append(
            f"| `{row['event_id']}` | {row['timestamp']} | {md_escape(row['service'])} | "
            f"{row['severity']} | {row['event_type']} | {md_escape(row['message'], 160)} | "
            f"{md_escape(', '.join(row['cited_by']))} |"
        )

    lines += ["", "## Missing evidence", ""]
    gaps = data["missing_evidence"] + data["data_quality"]
    lines += [f"- {md_escape(item, 400)}" for item in gaps] or ["- None recorded."]

    lines += ["", "## Recommended investigations", ""]
    lines += [
        f"{item['rank']}. **{md_escape(item['service'])}**: {md_escape(item['step'], 600)}"
        for item in data["recommended_investigations"]
    ] or ["1. Collect more evidence (see Missing evidence)."]

    comparison = data["comparison"]
    if comparison:
        lines += ["", "## Comparison with baseline", ""]
        status = "comparable" if comparison["comparable"] else "not comparable"
        lines.append(
            f"Comparison `{comparison['comparison_id']}` ({status}): "
            f"{md_escape(comparison['baseline']['label'])} vs "
            f"{md_escape(comparison['target']['label'])}."
        )
        lines += [f"- Not comparable: {md_escape(r)}" for r in comparison["incomparable_reasons"]]
        lines += [f"- Warning: {md_escape(w)}" for w in comparison["warnings"]]
        lines += [f"- {md_escape(f['text'])}" for f in comparison["findings"]]

    check = data["event_id_check"]
    lines += [
        "",
        "---",
        f"Event ID check: {check['verified']} of {check['referenced']} referenced event IDs "
        "were verified to exist in the source import.",
        "",
    ]
    return "\n".join(lines)
