# ADR 0006: AI explanations are optional, constrained and verified

**Status:** accepted

## Context

A language model can turn computed evidence into readable prose. It can also invent facts, follow instructions embedded in logs, or leak sensitive data.

## Decision

* The deterministic template is the default, and no feature depends on AI.
* The only provider is Anthropic, used through its official Python SDK (an optional extra), with structured JSON output, SDK-level timeouts and a bounded number of retries.
* The model receives only GhostTrace-computed facts. Raw log messages are sent only with an explicit opt-in, and they are delimited as untrusted data.
* The output is re-validated against a Pydantic schema. Every cited event ID must be in the incident's evidence set. Any failure, including refusals and truncated output, falls back to the template and records the reason.

## Consequences

* An AI answer can only rephrase and prioritise evidence that GhostTrace already found, and it is always labelled.
* Tests cover the guard rails with a fake provider and a stubbed SDK client. No test calls a real API.
