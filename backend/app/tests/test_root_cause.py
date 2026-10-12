"""Ranking regression tests on the fixed demo seed (42).

These scenarios were also used while developing the heuristics, so they guard against
regressions; the benchmark suite evaluates on separate, held-out seeds.
"""

from __future__ import annotations

import pytest

from app.services.analysis import analyze
from app.services.root_cause import WEIGHTS
from app.tests.factories import scenario_events

EXPECTED_ROOTS = {
    "db-connection-exhaustion": "orders-db",
    "downstream-api-timeout": "payment-provider",
    "faulty-deployment": "inventory-service",
    "retry-storm": "orders-service",
    "cache-failure": "redis-cache",
}


def test_weights_sum_to_one() -> None:
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


@pytest.mark.parametrize(("scenario", "root"), sorted(EXPECTED_ROOTS.items()))
def test_known_scenarios_rank_ground_truth_first(scenario: str, root: str) -> None:
    result = analyze(scenario_events(scenario))
    assert len(result.incidents) == 1
    ranking = result.incidents[0].ranking
    assert ranking.evidence_status == "sufficient"
    assert ranking.hypotheses[0].service == root


def test_ambiguous_scenario_reports_insufficient_evidence() -> None:
    result = analyze(scenario_events("ambiguous-partition"))
    ranking = result.incidents[0].ranking
    assert ranking.evidence_status == "insufficient"
    assert "Insufficient evidence" in ranking.evidence_summary
    assert all(h.uncertainty == "high" for h in ranking.hypotheses)
    assert any("trace ID" in item for item in ranking.missing_information)


def test_inferred_dependency_is_labelled() -> None:
    ranking = analyze(scenario_events("downstream-api-timeout")).incidents[0].ranking
    top = ranking.hypotheses[0]
    assert top.candidate_kind == "inferred"
    assert any("emits no events" in item for item in top.missing_information)


def test_retry_storm_victim_carries_contradiction() -> None:
    ranking = analyze(scenario_events("retry-storm")).incidents[0].ranking
    victim = next(h for h in ranking.hypotheses if h.service == "inventory-service")
    assert any(c.name == "overload_under_retry_storm" for c in victim.contradictions)


def test_hypotheses_are_evidence_linked_and_bounded() -> None:
    events = scenario_events("cache-failure")
    ids = {event.event_id for event in events}
    ranking = analyze(events).incidents[0].ranking
    for hypothesis in ranking.hypotheses:
        assert 0.0 <= hypothesis.score <= 1.0
        assert hypothesis.supporting_event_ids
        assert set(hypothesis.supporting_event_ids) <= ids
        for signal in hypothesis.signals:
            assert set(signal.evidence_event_ids) <= ids
            assert signal.contribution == pytest.approx(signal.weight * signal.value, abs=1e-3)
        assert hypothesis.as_dict()["score_label"] == "heuristic score (not a probability)"
        assert hypothesis.next_step
    ranks = [h.rank for h in ranking.hypotheses]
    assert ranks == list(range(1, len(ranks) + 1))
    scores = [h.score for h in ranking.hypotheses]
    assert scores == sorted(scores, reverse=True)


def test_ranking_is_deterministic() -> None:
    events = scenario_events("faulty-deployment")
    first = [h.as_dict() for h in analyze(events).incidents[0].ranking.hypotheses]
    second = [h.as_dict() for h in analyze(list(reversed(events))).incidents[0].ranking.hypotheses]
    assert first == second


def test_deployment_hypothesis_points_at_change_event() -> None:
    events = scenario_events("faulty-deployment")
    top = analyze(events).incidents[0].ranking.hypotheses[0]
    deployment = next(e for e in events if e.event_type == "deployment")
    assert top.key_event_id == deployment.event_id
    assert "2.3.1 -> 2.4.0" in top.next_step
