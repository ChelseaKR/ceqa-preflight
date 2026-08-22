# Data Card: Local Filing Packages

## Classification and purpose

Input packages may contain personal names, addresses, environmental locations,
and project records. Treat them as Tier L3 sensitive operational data. The
tool reads packages solely to produce a local advisory report.

## Processing and retention

Processing occurs on the operator's machine. The default `check` path makes
no runtime network request, sends no telemetry, and does not retain package
content after the process exits. Output reports are written only when the
operator chooses an output path and remain under that operator's control.

The opt-in `ai` commands ([ADR 0002](../adr/0002-ai-at-the-edges.md)) are a
separate data flow: they send extracted document text, or a report's findings,
to the configured model provider (the Anthropic API or Amazon Bedrock) for the
duration of that request. The provider's own processing and retention terms
apply to that request. The commands state this before running, never write the
text they send to a log or a file, and write their output only to a path the
operator chooses. An operator who cannot accept the provider's terms for a
package must not run the `ai` commands on it; `check` is unaffected.

Provider data-flow language reviewed and approved by the maintainer on
2026-08-22 (owner sign-off for the ADR 0002 direction).

## Restrictions

Do not commit real packages or reports to this repository. Use synthetic,
permissioned, or appropriately redacted fixtures for testing. Report a privacy
concern through the process in [SECURITY.md](../../SECURITY.md).
