"""Deterministic synthetic incident generation.

The simulator is used for the bundled demo datasets, tests and the benchmark suite. It is
never imported by the analysis engine, and ground-truth labels are returned separately
from the events so they cannot leak into prediction.
"""

from app.simulation.scenarios import SCENARIOS, GeneratedScenario, generate_scenario

__all__ = ["SCENARIOS", "GeneratedScenario", "generate_scenario"]
