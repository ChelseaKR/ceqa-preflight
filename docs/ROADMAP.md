# Roadmap

## 2026-07-18 — Foundation (complete)

- Local package loader, bounded PDF inspection, report renderers, declarative
  source-cited rules, and tests.
- Metric baseline: `make verify` is the merge gate; branch coverage threshold
  is 90%; no runtime network calls or retained package data.

## Now — Permissioned practitioner pilot (in progress)

- **Done:** local controlled-label pilot evidence kit (`pilot init` and
  `pilot summarize`); it stores no package content or free-text rationale.
- **In progress:** validate NOE and NOD rule wording with official sources and
  qualified users.
- **Blocked externally:** recruit participating organizations, obtain written
  package permission, and secure two qualified reviewers per activated rule.
- Measure false-positive rate and reviewer time on synthetic or permissioned
  packages; publish aggregate results only.
- Exit criteria: at least two qualified reviewers approve each activated rule;
  no untriaged high-severity parser or privacy finding.

## Before first tagged release

- Complete an accessibility review of console and HTML outputs with recorded
  assistive-technology evidence.
- Publish a residual-risk review, SBOM, provenance, and release notes.
- Exit criteria: all CI/security checks green, release checklist signed,
  no open critical vulnerability, and the release remains advisory-only.

## Not planned

- Hosted document storage, automatic CEQA submission, legal sufficiency
  determinations, or model-driven legal advice.
