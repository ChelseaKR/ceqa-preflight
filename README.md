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
technical inspection, a source-cited declarative rule engine, a common
technical rule pack (readability, searchable text, flattened forms, structure
tags, file hygiene), and a synthetic-package generator for demos and pilot
calibration. NOD- and NOE-specific rules are currently
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
    uv run ceqa-preflight init ./my-package --filing-type NOE --from-package
    uv run ceqa-preflight check ./my-package --filing-type NOE --format html --output ./reports
    uv run ceqa-preflight check ./my-package --filing-type NOE --include-experimental
    uv run ceqa-preflight check ./pkg-a ./pkg-b --filing-type NOE --format json --output ./reports
    uv run ceqa-preflight check ./my-package --filing-type NOE --format checklist
    uv run ceqa-preflight synth ./demo-package --filing-type NOE --defect scanned
    uv run ceqa-preflight rules list --filing-type NOE
    uv run ceqa-preflight rules list --format json
    uv run ceqa-preflight pilot init ./pilot-evidence
    uv run ceqa-preflight pilot summarize --reviews ./pilot-evidence/finding-review.csv --baseline ./pilot-evidence/manual-baseline.csv

Without a local checkout, run the CLI directly from a clone with
[uv](https://docs.astral.sh/uv/): `uvx --from /path/to/ceqa-preflight
ceqa-preflight --help`, or install it with `pipx install
/path/to/ceqa-preflight`. No package registry release exists yet.

The `check` command reads one or more directories or ZIP packages locally,
never uploads or alters their contents, and can emit console, JSON,
self-contained HTML, or printable sign-off checklist advisory reports.
Checking several packages at once prints a per-package roll-up summary. Add
`--manifest package.yaml` to enable explicit primary form and
document-category checks when experimental rules are opted into (single
package only), and `--rules` / `--exclude-rules` to select specific rule
identifiers. The default run includes active technical checks only. Add
`--log-format json` for minimal, package-content-free operational events on
stderr, including inspection progress counts for large packages.

The `synth` command generates plainly fictional synthetic packages, optionally
seeded with objective defects (scanned pages, fillable forms, encrypted or
truncated PDFs, duplicates, and more) for demos, regression tests, and pilot
reviewer calibration. See [examples/](examples/README.md) for a generated
package and its HTML report.

The `pilot` commands support the permissioned evaluation protocol with opaque
IDs and controlled labels only; they do not read filing packages or accept
free-text reviewer notes.

### Exit codes

`check` exits `0` when no automated failure was found (warnings and
manual-review items may still exist), `1` when at least one failure finding
was produced, and `2` on input or internal rule errors. With multiple
packages, the worst exit code wins.

## Non-affiliation and disclaimer

CEQA Preflight is an independent open-source project. It is not affiliated
with, endorsed by, or operated by the State of California, the Governor's
Office of Land Use and Climate Innovation, the State Clearinghouse, CEQA
Submit, or CEQAnet. See [DISCLAIMER.md](DISCLAIMER.md).

## Development

    make verify

This project is developed with AI-assisted tooling. Every change, whether
AI-assisted or not, must pass the same review, tests, and `make verify` gate
before merge; AI-assisted development measurement is tracked in the
[responsible technology audits](docs/RESPONSIBLE-TECH-AUDITS.md).

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

This project follows the vendored [Portfolio Standards](docs/standards/README.md).
“Applies” means an automated or documented
control exists; release-only evidence is collected before a tagged release.

| Standard | Status | Evidence / scope |
| --- | --- | --- |
| Code Quality | Applies | `Makefile` gates (ruff, mypy `--strict`, pytest with 90% branch-coverage floor, complexity <= 10), `uv.lock`, `.python-version` |
| Documentation | Applies | README, [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md), [CITATION.cff](CITATION.cff), [definition of done](DEFINITION_OF_DONE.md) |
| Quality & Metrics | Applies | [Metrics ledger](docs/ROADMAP.md#metrics-ledger) in the roadmap; `make verify` is the merge gate |
| CI/CD | Applies | SHA-pinned, permission-scoped workflows; CI runs the same `make verify` gate as local development |
| Security & Supply-Chain | Applies | [Security policy](SECURITY.md); bandit, pip-audit, gitleaks, and CodeQL in CI; SHA-pinned actions and a committed lockfile |
| Responsible-Tech Framework | Applies | [Responsible technology audits](docs/RESPONSIBLE-TECH-AUDITS.md), [threat model](docs/threat-model.md), [data card](docs/data/local-filing-packages.md) |
| Accessibility | Applies | [Accessibility boundaries](docs/accessibility.md); release review pending first tag |
| Observability | N/A (no hosted telemetry) | Stateless local CLI; opt-in JSON operational events only, no package contents |
| Internationalization (i18n/l10n) | Applies; pre-release gap | [Scope and release gate](docs/I18N.md); current English-only reports must gain reviewed EN/ES catalogs before a public tag |
| Performance | N/A (no service SLO) | No hosted service; bounded PDF/ZIP parsing is in the threat model |
| AI Evaluation | N/A (no AI runtime) | No model, prompt, or AI inference is shipped |
| Data governance | Applies | [Local filing package data card](docs/data/local-filing-packages.md) |

The central standards register is maintained separately and must be updated
when this repository is published.
