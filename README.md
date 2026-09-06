# CEQA Preflight

CEQA Preflight is a local-first command-line tool for checking the technical
readiness of CEQA Submit filing packages. It is pre-alpha, and what is
early-stage about it is the CEQA rule coverage rather than the engineering
around it; [Status](#status) states both, with the numbers.

It is designed to help planners, clerks, and consultants catch objective,
correctable package issues before State Clearinghouse review. It produces
source-cited advisory findings and human-review reminders; it will not submit
documents, modify originals, or determine legal sufficiency. The default
`check` path makes no network requests. A separate, opt-in `ai` command group
([ADR 0002](docs/adr/0002-ai-at-the-edges.md)) sends document text to a
configured model provider to draft manifest fields, explain findings, and
draft corrections; it never produces a finding and is never invoked by
`check`.

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

That is the early-stage part, and it is precise rather than a mood:
`ceqa-preflight rules list` reports 26 registered rules, of which 14 are active
and 12 are experimental, and the 12 experimental ones are exactly the NOD- and
NOE-specific rules. The domain half of the catalog is the unfinished half.

The engineering around it is not at that stage, and saying "early-stage" of the
whole tool understated it. `make verify` is the merge gate: 522 tests under a
90% branch-coverage floor, `strict = true` mypy over 38 source files, bandit,
and an i18n gate holding 210 English and Spanish messages at enforced parity.
The suite runs with sockets disabled (`--disable-socket` in `addopts`), so the
"no network requests" promise of the default `check` path is enforced rather
than asserted. None of that makes the tool production-ready: `0.1.0` is a
pre-release development baseline with no tag behind it, nothing is published to
a package registry, and the CLI and JSON report schema are still unstable.
See [Public API and release status](#public-api-and-release-status).

## Intended initial scope

- Local directory or ZIP input.
- NOD and NOE package checks.
- Deterministic PDF and metadata checks.
- Accessible HTML and JSON reports.
- No hosted document storage, portal scraping, or AI-driven legal analysis.
- Opt-in, model-backed drafting and explanation under
  [ADR 0002](docs/adr/0002-ai-at-the-edges.md): the model structures input
  and narrates cited sources; only the deterministic rule engine produces a
  finding, and legal-sufficiency questions are refused.

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
    uv run ceqa-preflight --locale es check ./my-package --filing-type NOE
    uv run ceqa-preflight diff ./reports/before.json ./reports/report.json
    uv run ceqa-preflight diff ./before.json ./after.json --format html --output ./comparison.html
    uv run ceqa-preflight synth ./demo-package --filing-type NOE --defect scanned
    uv run ceqa-preflight rules list --filing-type NOE
    uv run ceqa-preflight rules list --format json
    uv run ceqa-preflight pilot init ./pilot-evidence
    uv run ceqa-preflight pilot summarize --reviews ./pilot-evidence/finding-review.csv --baseline ./pilot-evidence/manual-baseline.csv

Without a local checkout, run the CLI straight from the default branch with
[uv](https://docs.astral.sh/uv/), or install it with `pipx`:

    uvx --from git+https://github.com/ChelseaKR/ceqa-preflight ceqa-preflight --help
    pipx install git+https://github.com/ChelseaKR/ceqa-preflight

Both track `main` rather than a fixed point, because no tag has been cut. These
two commands read `@v0.1.0` until 2026-09-06 and failed for everyone who ran
them: no such tag exists. `release.yml` is committed and will attach a built
wheel and sdist, a CycloneDX SBOM and build provenance to a GitHub Release when
a signed `v*` tag is pushed, and nothing is attached to anything yet. There is
no package-registry publication either, so plain `uvx ceqa-preflight` will not
find it. From a clone, `uvx --from /path/to/ceqa-preflight ceqa-preflight
--help` still works.

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

Every report states its own scope. Any rule that applies to the filing type but
did not run — because it is experimental and `--include-experimental` was not
given, because `--rules` or `--exclude-rules` removed it, or because it has been
withdrawn — is listed by identifier, with the reason and the way to run it, in
all four report formats. A report with no failures therefore always says whether
it covered every applicable check or only some of them.

### Comparing two reports

A package is usually checked, corrected, and checked again, and nothing said
what moved between the two runs. `diff` reads two JSON reports written by
`check` and names every finding that appeared, cleared, or changed, in console,
JSON or self-contained HTML through the same locale seam the reports use.

    uv run ceqa-preflight diff ./before.json ./after.json

It is deliberately unwilling to guess. Findings pair on rule identifier,
document and field, which is the only identity the report schema offers; where
that key is not unique on either side the pair is reported as **not comparable**
with both counts, rather than paired in list order and called a change. A rule
that did not run in one report and is absent from the other is **not
comparable** too — the second report says nothing about it, which is not the
same as the finding having cleared. Differences in `tool_version`,
`ruleset_version`, `filing_type` or `input_fingerprint` are stated before any
delta, because a check that "cleared" by leaving the ruleset is not a
correction. A report announcing a `report_schema_version` this tool does not
know is refused rather than compared. Two identical reports produce an explicit
no-change line naming the shared package fingerprint, never an empty screen.

`diff` exits `0` when nothing regressed, `1` when a failure is new or a finding
became one, and `2` when an input cannot be read as a comparable report. A
finding that no longer appears has cleared a technical check; it has not been
determined compliant, and the comparison says so on every format.

### Report language

Reports render in English by default and in Spanish with `--locale es`:

    uv run ceqa-preflight --locale es check ./my-package --filing-type NOE

`--locale` is the only thing that selects a language. `LANG`, `LC_ALL`, and
`LANGUAGE` are not read, and nothing is inferred from a network response or
from the contents of a filing package, so the same command line produces the
same report on any machine. A well-formed language tag with no catalog, such as
`fr`, renders in English and says on stderr which tag could not be met; a
malformed tag is a usage error rather than a silent downgrade.

Only prose moves. Rule identifiers, finding status values, JSON field names,
source citations, and the exit code are identical in every locale, so a
pipeline that gates on the report does not care which language a person reads
it in.

**The Spanish catalog is a maintainer draft.** A qualified Spanish-language
CEQA reviewer has not yet approved its terminology or its advisory, non-legal
framing; that review is
[issue #49](https://github.com/ChelseaKR/ceqa-preflight/issues/49) and it is
one of the conditions on a first tagged release. Until it is done the English
wording is authoritative, and every non-English run says so. See
[docs/I18N.md](docs/I18N.md).

The `synth` command generates plainly fictional synthetic packages, optionally
seeded with objective defects (scanned pages, fillable forms, encrypted or
truncated PDFs, duplicates, and more) for demos, regression tests, and pilot
reviewer calibration. See [examples/](examples/README.md) for a generated
package and its HTML report.

The `pilot` commands support the permissioned evaluation protocol with opaque
IDs and controlled labels only; they do not read filing packages or accept
free-text reviewer notes.

### Opt-in AI commands

The `ai` command group ([ADR 0002](docs/adr/0002-ai-at-the-edges.md)) is the
only part of the tool that talks to a model provider, and nothing else invokes
it. Install the extra (`pip install 'ceqa-preflight[ai]'`, or `[ai-bedrock]`
for Amazon Bedrock), put the credential in the environment
(`ANTHROPIC_API_KEY`, or the AWS credential chain plus `AWS_REGION`), and opt
in per command. The default model is `claude-sonnet-5` on the Anthropic API and
`claude-sonnet-4-6` on Bedrock, which is the model every recorded eval run was
produced on because Sonnet 5 answers 403 on the account this project has;
`--provider`, `--model`, `CEQA_PREFLIGHT_AI_PROVIDER`, and
`CEQA_PREFLIGHT_AI_MODEL` change either. Every `ai` command states the data flow before it runs: the text it sends
leaves the machine for the duration of the request, and the provider's terms
apply to it. It never writes that text to a log.

    uv run ceqa-preflight ai extract ./my-package --filing-type NOE --write-manifest ./my-package/package.yaml
    uv run ceqa-preflight ai extract ./my-package --filing-type NOE --format json --output ./reports/extraction.json

`ai extract` reads each PDF's text layer through the same bounded,
process-isolated path `check` uses and asks the model to copy out the facts a
manifest carries: what kind of document it is, the project title, lead agency,
county, city, SCH number, exemption status and citation, and so on. Every value
must come with a verbatim quote from the document; the tool verifies the quote
against the text and withholds any value whose quote does not verify. A field
the text does not state is `unknown`. A scanned, image-only PDF is reported as
having no text layer and is not sent anywhere. The result is a **draft**
manifest for a person to review and correct; only `check --manifest` on the
reviewed manifest produces findings. The model structures input. It never
decides anything, and the rule engine never sees its output directly.

    uv run ceqa-preflight check ./my-package --filing-type NOE --format json --output ./reports
    uv run ceqa-preflight ai explain ./reports/report.json
    uv run ceqa-preflight ai draft-fix ./reports/report.json --rules PDF-003,PDF-007
    uv run ceqa-preflight ai ask ./reports/report.json "What does PDF-003 mean?"

`ai explain` and `ai draft-fix` read a JSON report written by `check` and,
for each failure, warning, or manual-review item, ask the model for a
plain-language explanation (or a numbered correction draft) in which every
claim cites a passage of the official source the rule cites and quotes it
verbatim. The passages come from [`corpus/`](corpus/README.md), the committed,
hashed text of those sources; a verifier checks every quote against it and
checks every sentence for determination language before anything is shown.
Claims that fail are withheld and counted. A self-cited rule (FILE-004,
FILE-005) is explained from the project's own reasoning and says so.

`ai ask` answers questions about the findings in a report. Any form of "is
this legally sufficient", "will it be accepted", "is this exemption valid",
or "did the agency comply", in English or Spanish, direct or indirect, is
refused before the model runs and redirected to the objective findings and
to qualified review; the model is instructed to refuse as well, and its
answers pass the same verifier. The refusal suite in [`evals/`](evals/README.md)
has zero tolerance. None of this output is a finding; `check` alone produces
findings, and its output is unchanged by the `ai` commands.

### Exit codes

`check` exits `0` when no automated failure was found (warnings and
manual-review items may still exist), `1` when at least one failure finding
was produced, and `2` on input or internal rule errors. With multiple
packages, the worst exit code wins.

Exit code `0` is not a statement that every applicable check ran: skipped
checks do not change it. Read the `not_run` list, or the "check(s) not run"
count in the summary line, before treating a `0` as a complete result.

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
architecture decisions
([ADR 0001](docs/decisions/0001-local-first-deterministic-cli.md),
[ADR 0002](docs/adr/0002-ai-at-the-edges.md)).
The project also documents its [pilot protocol](docs/pilot-protocol.md),
[pilot partner kit](docs/pilot-partner-kit.md),
[accessibility boundaries](docs/accessibility.md), and
[threat model](docs/threat-model.md).

## Public API and release status

The command-line interface and JSON report schema are **not yet stable**.
`0.1.0` is the pre-release development baseline, and no tag has been cut for
it: `git tag --list` is empty on this repository, there is no GitHub Release,
and nothing has been released. It is a version number, not a promise of
production readiness and not an artifact you can install. `tests/test_release_claims.py`
reads the tags and fails if that stops being said here while it stays true.
Under the 0ver intent of the
[Release & Versioning standard](docs/standards/RELEASE-AND-VERSIONING-STANDARD.md)
(§2, REL-05), a `MINOR` bump before `1.0.0` may break. No package-registry
publication has been made. See [CHANGELOG.md](CHANGELOG.md) and
[docs/ROADMAP.md](docs/ROADMAP.md).

## Standards conformance

This project follows the vendored [Portfolio Standards](docs/standards/README.md).
“Applies” means an automated or documented
control exists; release-only evidence is collected before a tagged release.

| Standard | State | Evidence / scope |
| --- | --- | --- |
| Responsible-Tech Framework | Applies | [Responsible technology audits](docs/RESPONSIBLE-TECH-AUDITS.md), [threat model](docs/threat-model.md), and [data card](docs/data/local-filing-packages.md) |
| Code Quality | Applies | `Makefile` gates (ruff, mypy `--strict`, pytest with a 90% branch-coverage floor, and complexity <= 10), `uv.lock`, and `.python-version` |
| Security & Supply-Chain | Applies | [Security policy](SECURITY.md); bandit, pip-audit, gitleaks, and CodeQL in CI; SHA-pinned actions and a committed lockfile |
| CI/CD | Applies | SHA-pinned, permission-scoped workflows; CI runs the same `make verify` gate as local development |
| Release & Versioning | Applies -- not met | `0.1.0` is declared in `pyproject.toml` and `CITATION.cff` and no tag has been cut, so nothing has been released: no signed tag, no GitHub Release, no SBOM or provenance attached to anything, no package-registry publication. The signed-tag `release.yml` is committed and will do all of that when a `v*` tag is pushed, authorized against `.github/allowed_signers` with `make verify` re-run at the tagged commit; it has never run. `tests/test_release_claims.py` derives this row's state from `git tag --list` rather than restating it |
| Observability | N/A (no hosted telemetry) | Stateless local CLI; opt-in JSON operational events only, with no package contents |
| Performance | N/A (no service SLO) | No hosted service; bounded PDF/ZIP parsing is covered by the threat model |
| Accessibility | Applies | [Accessibility boundaries](docs/accessibility.md); release review pending the first tag |
| Internationalization | Applies — seam merged, review outstanding | [Scope and release gate](docs/I18N.md); EN and ES catalogs ship at enforced parity (`make i18n`), and the Spanish draft still needs qualified CEQA terminology review before a public tag ([#49](https://github.com/ChelseaKR/ceqa-preflight/issues/49)) |
| AI Evaluation | Applies | [ADR 0002](docs/adr/0002-ai-at-the-edges.md); the committed [`evals/`](evals/README.md) harnesses (legal-sufficiency refusal, real-filing extraction vs. CEQAnet metadata, citation grounding) with provenance-stamped results; a test rejects any result file without provenance |
| Documentation | Applies | README, [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md), [CITATION.cff](CITATION.cff), and the [definition of done](DEFINITION_OF_DONE.md) |
| Quality & Metrics | Applies | [Metrics ledger](docs/ROADMAP.md#metrics-ledger) in the roadmap; `make verify` is the merge gate |
| AI Development Measurement | Applies | `docs/ROADMAP.md` declares `AI-DEV-MEASUREMENT: APPLIES`; the baseline is recorded in the [responsible technology audits](docs/RESPONSIBLE-TECH-AUDITS.md) |
| Incident Response | Applies — local CLI scope | Security, privacy, and data-exposure incidents remain in scope even though there is no hosted service |
| Data Governance | Applies | The [local filing package data card](docs/data/local-filing-packages.md) defines the processing and retention boundary |

The central standards register is maintained separately and must be updated
when this repository is published.
