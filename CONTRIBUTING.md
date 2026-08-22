# Contributing

Thanks for improving CEQA Preflight.

## Before contributing

- Read [DISCLAIMER.md](DISCLAIMER.md) and [GOVERNANCE.md](GOVERNANCE.md).
- Do not submit real filing packages, personal information, confidential
  locations, or copyrighted third-party documents without explicit permission.
- Do not add a CEQA-specific rule without a current official source and tests.
- Keep the default `check` path local; do not add telemetry or network calls
  to it. Model calls live only in the opt-in `ai` command group
  ([ADR 0002](docs/adr/0002-ai-at-the-edges.md)), import the SDK lazily, and
  never produce a finding.
- Read the vendored [Portfolio Standards](docs/standards/README.md); project-specific
  applicability is declared in the README.

## Development setup

    uv sync --all-groups
    make verify

## Pull requests

Keep each pull request narrowly scoped. Include tests and documentation for
behavior changes. Explain any source, rule-version, or accessibility impact.

Run `pre-commit run --all-files` and `make verify` before opening a pull
request. Changes to rules, data handling, or output must update the relevant
audit, data-card, and/or accessibility evidence.

For rule changes, link to the traceability entry and identify the qualified
reviewer. Do not claim that a rule establishes legal sufficiency.
