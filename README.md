# CEQA Preflight

CEQA Preflight is an early-stage, local-first command-line tool for checking
the technical readiness of CEQA Submit filing packages.

It is designed to help planners, clerks, and consultants catch objective,
correctable package issues before State Clearinghouse review. It will produce
source-cited advisory findings and human-review reminders; it will not submit
documents, modify originals, make network requests at runtime, or determine
legal sufficiency.

## Status

**Status:** In build

CEQA Preflight is pre-alpha software. The repository includes safe local package loading, bounded PDF
technical inspection, a source-cited declarative rule engine, and an initial
common technical rule pack. NOD- and NOE-specific rules are currently
**experimental**: they run only with `--include-experimental` while documented
official-source review, practitioner review, tests, and a permissioned pilot
are completed.

## Intended initial scope

- Local directory or ZIP input.
- NOD and NOE package checks.
- Deterministic PDF and metadata checks.
- Accessible HTML and JSON reports.
- No hosted document storage, portal scraping, or AI-driven legal analysis.

## Quick start

    uv sync --all-groups
    uv run ceqa-preflight --version
    uv run ceqa-preflight --help
    uv run ceqa-preflight init ./my-package --filing-type NOE
    uv run ceqa-preflight check ./my-package --filing-type NOE --format html --output ./reports
    uv run ceqa-preflight check ./my-package --filing-type NOE --include-experimental
    uv run ceqa-preflight rules list --filing-type NOE
    uv run ceqa-preflight pilot init ./pilot-evidence
    uv run ceqa-preflight pilot summarize --reviews ./pilot-evidence/finding-review.csv --baseline ./pilot-evidence/manual-baseline.csv

The `check` command reads a directory or ZIP package locally, never uploads or
alters its contents, and can emit console, JSON, or self-contained HTML
advisory reports. Add `--manifest package.yaml` to enable explicit primary
form and document-category checks when experimental rules are opted into. The
default run includes active technical checks only. Add `--log-format json` for
minimal, package-content-free operational events on stderr.

The `pilot` commands support the permissioned evaluation protocol with opaque
IDs and controlled labels only; they do not read filing packages or accept
free-text reviewer notes.

## Non-affiliation and disclaimer

CEQA Preflight is an independent open-source project. It is not affiliated
with, endorsed by, or operated by the State of California, the Governor's
Office of Land Use and Climate Innovation, the State Clearinghouse, CEQA
Submit, or CEQAnet. See [DISCLAIMER.md](DISCLAIMER.md).

## Development

    make verify

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the
[architecture decision](docs/decisions/0001-local-first-deterministic-cli.md).
The project also documents its [pilot protocol](docs/pilot-protocol.md),
[pilot partner kit](docs/pilot-partner-kit.md),
[accessibility boundaries](docs/accessibility.md), and
[threat model](docs/threat-model.md).

## Public API and release status

The command-line interface and JSON report schema are **not yet stable**. No
GitHub Release or package publication has been made; version `0.1.0` is the
pre-release development baseline, not a promise of production readiness.
Breaking changes may occur before the first tagged release. See
[CHANGELOG.md](CHANGELOG.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## Standards conformance

This project follows the pinned [Portfolio Standards](STANDARDS/README.md)
submodule at release `v1.0.1`. “Applies” means an automated or documented
control exists; release-only evidence is collected before a tagged release.

| Standard | Status | Evidence / scope |
| --- | --- | --- |
| Core delivery, documentation, quality | Applies | `Makefile`, CI, [definition of done](DEFINITION_OF_DONE.md) |
| Security, supply chain, responsible technology | Applies | [security policy](SECURITY.md), [audits](docs/RESPONSIBLE-TECH-AUDITS.md) |
| Accessibility | Applies | [accessibility boundaries](docs/accessibility.md); release review pending first tag |
| Observability | N/A hosted telemetry | Stateless local CLI; opt-in JSON operational events only, no package contents |
| i18n/l10n | N/A current scope | English-only operator tool; no public-service transaction UI |
| Performance | N/A service SLO | No hosted service; bounded PDF/ZIP parsing is in the threat model |
| AI evaluation | N/A runtime | No model, prompt, or AI inference is shipped |
| Data governance | Applies | [local filing package data card](docs/data/local-filing-packages.md) |

The central standards register is maintained separately and must be updated
when this repository is published.
