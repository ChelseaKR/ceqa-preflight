# Responsible Technology Audits

CEQA Preflight performs deterministic, local checks over potentially sensitive
filing packages. It is advisory software, not a public decision system.

| Date | Scope | Result | Evidence / follow-up |
| --- | --- | --- | --- |
| 2026-07-18 | Baseline privacy, security, accessibility, and misuse review | Conditional pass for public pre-alpha repository | [Threat model](threat-model.md), [data card](data/local-filing-packages.md), [risk register](audits/residual-risk-register-2026-07-18.md) |
| 2026-07-18 | AI-assisted development measurement | Baseline recorded; no AI runtime feature | Code and documentation are independently tested and reviewed before merge; reassess at first tagged release (2026-10-18 target) |
| 2026-07-18 | Filing-rule source freshness | Official guidance reviewed; NOD/NOE rules remain experimental pending qualified practitioner evidence | [Source review](audits/rule-source-review-2026-07-18.md) |

## Release gate

Before each tagged release, a maintainer records: test/security results,
dependency and SBOM review, representative HTML and console accessibility
checks, source freshness for activated rules, and unresolved residual risks.
No tagged release has occurred yet.
