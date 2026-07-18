# Residual Risk Register — 2026-07-18

| Risk | Residual level | Control | Owner / trigger |
| --- | --- | --- | --- |
| Malformed ZIP/PDF consumes local resources | Medium | File-count, size, and parser bounds; spawned inspection | Maintainer; investigate parser failure or resource exhaustion |
| Rule output is mistaken for legal sufficiency | Medium | Advisory language, disclaimers, source citations, pilot review | Maintainer; review all rule wording changes |
| Input package includes sensitive data | Low | Local-only processing, no telemetry, contributor restrictions | Operator; never commit real packages |
| HTML report is inaccessible in a reader/browser combination | Medium | Semantic report templates and documented release accessibility gate | Maintainer; test before each release |
| Supply-chain compromise | Medium | Lockfile, dependency audit, CodeQL, gitleaks, pinned actions, SBOM/provenance release workflow | Maintainer; triage alert within 72 hours |
