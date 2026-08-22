# Roadmap

## 2026-07-18 — Foundation (complete)

- Local package loader, bounded PDF inspection, report renderers, declarative
  source-cited rules, and tests.
- Metric baseline: `make verify` is the merge gate; branch coverage threshold
  is 90%; no runtime network calls or retained package data.

## Now — Permissioned practitioner pilot (in progress)

- **Done:** local controlled-label pilot evidence kit (`pilot init` and
  `pilot summarize`); it stores no package content or free-text rationale.
- **Done:** desk review of current official LCI State Clearinghouse guidance;
  NOD/NOE-specific rules are explicitly gated as experimental. See the
  [source review](audits/rule-source-review-2026-07-18.md).
- **Done:** participant outreach and evaluation materials that preserve the
  local, permissioned pilot boundary. See the
  [pilot partner kit](pilot-partner-kit.md).
- **Done:** a synthetic-package generator (`ceqa-preflight synth`) with
  seedable, objective defects, so reviewer calibration, demos, and
  false-positive measurement can begin before any real package permission is
  granted. A committed example lives in `examples/`.
- **In progress:** validate NOE and NOD rule wording with qualified users.
- **Blocked externally:** recruit participating organizations, obtain written
  package permission, and secure two qualified reviewers per activated rule.
- Measure false-positive rate and reviewer time on synthetic or permissioned
  packages; publish aggregate results only.
- Exit criteria: at least two qualified reviewers approve each activated rule;
  no untriaged high-severity parser or privacy finding.

## Before first tagged release

- Complete an accessibility review of console and HTML outputs with recorded
  assistive-technology evidence.
- Implement the [internationalization release gate](I18N.md): gettext entry
  point, reviewed English and Spanish catalogs, catalog parity checks, and
  deterministic CLI locale selection.
- Publish a residual-risk review, SBOM, provenance, and release notes.
- Exit criteria: all CI/security checks green, release checklist signed,
  no open critical vulnerability, and the release remains advisory-only.

## Now — Opt-in AI layer (ADR 0002)

- **Done:** [ADR 0002](adr/0002-ai-at-the-edges.md); `ai extract` (quote-verified
  draft manifest), `ai explain` and `ai draft-fix` (corpus-grounded, verified
  claims), and `ai ask` behind the deterministic legal-sufficiency guard. The
  rule engine remains the only source of findings; `check` is unchanged.
- **Done:** committed `corpus/` of the official sources the rules cite, with
  hashes and retrieval dates, and the verifier that checks every quote.
- **Done:** committed `evals/` harnesses and first live results (see
  [evals/README.md](../evals/README.md)): refusal suite, real-filing
  extraction against CEQAnet metadata, and citation grounding.
- **Done:** the CEQA Guidelines (14 CCR § 15000 et seq.) are in the corpus,
  retrieved section by section from the official online CCR with the
  publisher's currency statement recorded as each document's edition (see
  [corpus/README.md](../corpus/README.md)); the NOD and NOE rules are wired to
  the sections governing their forms for explanation retrieval only.
- **Open:** the default model `claude-sonnet-5` has not been run live (the
  recorded runs used Bedrock `claude-sonnet-4-6`); a qualified CEQA reviewer
  and a native Spanish reader have not reviewed the prompts, the refusal
  cases, the Spanish phrasings, or the retained Guidelines text
  ([#49](https://github.com/ChelseaKR/ceqa-preflight/issues/49)); the `ai`
  strings await the gettext seam ([#39](https://github.com/ChelseaKR/ceqa-preflight/issues/39)).

## Not planned

- Hosted document storage, automatic CEQA submission, legal sufficiency
  determinations, or model-driven legal advice. The AI layer narrates cited
  sources and structures input; it does not evaluate sufficiency.

## Metrics ledger

Last reviewed: 2026-08-07. Owner: maintainer. This is the enforcement ledger
required by the portfolio Quality & Metrics standard: each row is an AUTO gate
(merge-blocking), a REVIEW gate with a durable evidence artifact, or an
explicit N/A with a reason. Values are project-specific; the rigor is defined
by the owning standard.

| Metric | Target | Measured by | Gate | Owner |
| --- | --- | --- | --- | --- |
| Branch coverage | >= 90% | `make test` (pytest-cov, `fail_under = 90`) in CI | AUTO | Maintainer |
| Lint / format / types | 0 errors | `make lint` (ruff), `make typecheck` (mypy `--strict`) | AUTO | Maintainer |
| Cyclomatic complexity | <= 10 per function | ruff C90 in `make lint` | AUTO | Maintainer |
| Static security findings | 0 unresolved | `make security` (bandit) and CodeQL in CI | AUTO | Maintainer |
| Known-vulnerable dependencies | 0 in `uv.lock` | `make audit` (pip-audit) in CI | AUTO | Maintainer |
| Secret leaks | 0 | gitleaks in the security workflow | AUTO | Maintainer |
| SHA-pinned workflow `uses:` | 100% | portfolio conformance tripwire (weekly) plus PR review | REVIEW | Maintainer |
| EN/ES catalog parity | 100% keys and placeholders before first public tag | [i18n release gate](I18N.md); not yet implemented (pre-release gap) | REVIEW | Maintainer |
| Accessibility review of console/HTML output | Recorded assistive-technology evidence per release | Release checklist; no tagged release yet | REVIEW | Maintainer |
| Pilot false-positive rate | Measured on synthetic or permissioned packages; aggregate results only | `pilot summarize` evidence kit | REVIEW | Maintainer |

`AI-DEV-MEASUREMENT: APPLIES`. Development is AI-assisted; delivery and
quality-debt metrics are measured by portfolio automation from Git and CI.
With [ADR 0002](adr/0002-ai-at-the-edges.md), Track B product evaluations
apply to the opt-in `ai` commands; their evidence is the committed `evals/`
harness and its provenance-stamped results (see the
[responsible technology audits](RESPONSIBLE-TECH-AUDITS.md)).
