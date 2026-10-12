# Contributing to GhostTrace

Thanks for your interest! Issues and pull requests are welcome.

## Development setup

Follow "Run it on Windows" in the [README](README.md). The same commands work on macOS and Linux with `.venv/bin/python`.

## Before opening a pull request

Run the same checks as CI:

```powershell
# from backend/
.\.venv\Scripts\python.exe -m ruff check --config pyproject.toml . ..\scripts ..\benchmarks
.\.venv\Scripts\python.exe -m ruff format --config pyproject.toml . ..\scripts ..\benchmarks
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest

# from frontend/
npm run lint; npm run typecheck; npm test; npm run build
npx playwright test e2e/incident-flow.spec.ts
```

## Guidelines

* **Keep analysis code pure.** `backend/app/services/*` must not import FastAPI or touch the database, so it stays testable and benchmarkable.
* **Evidence first.** Any new signal or heuristic must cite event IDs and be documented in `docs/analysis.md`. Never present a heuristic as a probability or a proven cause.
* **Determinism.** Same input, same output. Sort by `(timestamp, event_id)` and avoid wall-clock time or randomness in analysis.
* **Schema changes** need an Alembic migration (`python -m alembic revision --autogenerate -m "..."`); review the generated file before committing.
* **Synthetic data.** If you change the simulator, regenerate the datasets with `python scripts\generate_datasets.py` and commit the updated `datasets/` and `MANIFEST.json`. Never pass ground truth to the engine.
* **Benchmarks.** Don't tune heuristics against the held-out seeds (2001+). Use seed 42 or new development seeds, and report benchmark changes honestly in `benchmarks/README.md`.
* **Tests.** New behaviour needs tests. Fix failing tests rather than weakening them.
* **UI.** Every control must do what it says. Show loading, empty and error states, and keep components accessible (labels, keyboard support, contrast).

## Commit messages

Use short, imperative [Conventional Commits](https://www.conventionalcommits.org/) prefixes, for example `feat(replay): add jump-to-event`, `fix(graph): …` or `docs: …`.

## Reporting security issues

Please use a private GitHub security advisory rather than a public issue (see [docs/security.md](docs/security.md)).
