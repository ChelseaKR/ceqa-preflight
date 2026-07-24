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

## Not planned

- Hosted document storage, automatic CEQA submission, legal sufficiency
  determinations, or model-driven legal advice.
