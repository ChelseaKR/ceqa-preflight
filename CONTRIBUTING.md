# Contributing

Thanks for improving CEQA Preflight.

## Before contributing

- Read [DISCLAIMER.md](DISCLAIMER.md) and [GOVERNANCE.md](GOVERNANCE.md).
- Do not submit real filing packages, personal information, confidential
  locations, or copyrighted third-party documents without explicit permission.
- Do not add a CEQA-specific rule without a current official source and tests.
- Periodically confirm rule source citations still resolve with
  `make audit-sources` (network access required; not part of `make verify`).
- Keep the default `check` path local; do not add telemetry or network calls
  to it. Model calls live only in the opt-in `ai` command group
  ([ADR 0002](docs/adr/0002-ai-at-the-edges.md)), import the SDK lazily, and
  never produce a finding.
- Read the vendored [Portfolio Standards](docs/standards/README.md); project-specific
  applicability is declared in the README.

## Development setup

    uv sync --all-groups
    make verify

## User-visible strings

Anything a person reads goes through the gettext seam: `from
ceqa_preflight.i18n import gettext as _`, then `_("…")` with `{name}`
placeholders. Rule identifiers, finding status values, JSON field names,
command names, and source citations are stable identifiers and stay out of the
catalogs. After adding or rewording a string, run `make i18n-update`, carry the
message into `en` and `es`, and translate it. `make verify` fails while any
message is unextracted, untranslated, fuzzy, or out of placeholder parity.
[docs/I18N.md](docs/I18N.md) has the full loop and the reasoning.

## Pull requests

Keep each pull request narrowly scoped. Include tests and documentation for
behavior changes. Explain any source, rule-version, or accessibility impact.

Run `pre-commit run --all-files` and `make verify` before opening a pull
request. Changes to rules, data handling, or output must update the relevant
audit, data-card, and/or accessibility evidence.

For rule changes, link to the traceability entry and identify the qualified
reviewer. Do not claim that a rule establishes legal sufficiency.
