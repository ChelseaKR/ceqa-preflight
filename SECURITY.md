# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability involving file
handling, report injection, privacy, or package parsing. Report it privately
through [GitHub private vulnerability reporting](https://github.com/ChelseaKR/ceqa-preflight/security/advisories/new).

Include:

- A clear description and impact.
- Reproduction steps or a minimal synthetic proof of concept.
- Affected version or commit.
- Any suggested mitigation.

## Security posture

CEQA Preflight is designed to process untrusted filing packages locally.
Security-sensitive work includes ZIP extraction, PDF parsing, output escaping,
dependency updates, and handling of project metadata.

The project aims to acknowledge reports within 72 hours and will share a
remediation timeline after triage. Until the first tagged release, only the
default branch is supported. Security controls, residual risks, and review
cadence are documented in [docs/RESPONSIBLE-TECH-AUDITS.md](docs/RESPONSIBLE-TECH-AUDITS.md).
