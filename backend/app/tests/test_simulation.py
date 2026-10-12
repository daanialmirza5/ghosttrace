from __future__ import annotations

import pytest

from app.services.normalization import normalize_record
from app.simulation import SCENARIOS, generate_scenario


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenarios_are_deterministic(name: str) -> None:
    first = generate_scenario(name, 42)
    second = generate_scenario(name, 42)
    assert first.sha256() == second.sha256()
    assert first.ground_truth == second.ground_truth


def test_different_seeds_produce_different_data() -> None:
    assert (
        generate_scenario("healthy-control", 1).sha256()
        != generate_scenario("healthy-control", 2).sha256()
    )


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_generated_event_is_valid(name: str) -> None:
    scenario = generate_scenario(name, 7)
    ids = [normalize_record(event).event.event_id for event in scenario.events]
    assert len(ids) == len(set(ids))
    assert 500 < len(ids) < 6000


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_ground_truth_is_not_embedded_in_events(name: str) -> None:
    scenario = generate_scenario(name, 42)
    forbidden = {"_gt", "_t", "ground_truth", "root_cause", "expected_outcome"}
    for event in scenario.events:
        assert forbidden.isdisjoint(event)
        assert forbidden.isdisjoint(event.get("attributes", {}))


def test_ground_truth_shape() -> None:
    truth = generate_scenario("faulty-deployment", 42).ground_truth
    assert truth["expected_outcome"] == "root_cause"
    assert truth["root_cause_service"] == "inventory-service"
    assert truth["fault_window"]["start"] < truth["fault_window"]["end"]
    assert len(truth["fault_event_ids"]) == 1


def test_external_dependency_never_emits_events() -> None:
    scenario = generate_scenario("downstream-api-timeout", 42)
    assert all(event["service"] != "payment-provider" for event in scenario.events)
    assert any(event.get("target_service") == "payment-provider" for event in scenario.events)


def test_ambiguous_scenario_has_no_linking_evidence() -> None:
    scenario = generate_scenario("ambiguous-partition", 42)
    for event in scenario.events:
        assert "trace_id" not in event
        assert "target_service" not in event
