# ADR 0000: Record architecture decisions

## Status

Accepted — 2026-07-18

## Context

CEQA Preflight must preserve clear, reviewable choices around local processing,
source-grounded rules, and safety boundaries.

## Decision

Architecture decisions are stored as immutable numbered Markdown records in
this directory. Existing decision 0001 is retained at
`docs/decisions/0001-local-first-deterministic-cli.md` and should be moved or
cross-referenced when it changes. [ADR 0002](0002-ai-at-the-edges.md) amends
it.

## Consequences

Significant changes to processing location, network behavior, rule execution,
data handling, or public interface require an ADR and a standards review.
