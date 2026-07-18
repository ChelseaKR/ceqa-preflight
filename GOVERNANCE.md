# Governance

CEQA Preflight is maintained as a narrow, evidence-backed open-source project.

## Maintainer responsibilities

Maintainers must:

- Keep the project advisory and local-first.
- Require an official source, effective date, tests, and reviewer approval for
  every active CEQA-specific rule.
- Publish material rule changes and deprecations in the changelog.
- Treat security, privacy, accessibility, and false-positive reports as
  release-blocking when appropriate.
- Avoid using real filing packages in the public repository.

## Rule changes

Any new or changed rule requires:

1. A traceable source URL and source section.
2. A statement of whether it is publication guidance, a legal requirement, or
   a technical security check.
3. Positive, negative, boundary, and indeterminate tests.
4. A named reviewer with relevant CEQA practice experience.
5. A semantic version change to the affected rule.

Rules without sufficient evidence remain manual-review items.

## Scope changes

New filing types, hosted processing, portal integrations, or AI features
require a documented architecture decision and pilot evidence. They cannot be
added as incidental enhancements.
