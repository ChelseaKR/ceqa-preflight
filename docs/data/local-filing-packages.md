# Data Card: Local Filing Packages

## Classification and purpose

Input packages may contain personal names, addresses, environmental locations,
and project records. Treat them as Tier L3 sensitive operational data. The
tool reads packages solely to produce a local advisory report.

## Processing and retention

Processing occurs on the operator's machine. CEQA Preflight makes no runtime
network request, sends no telemetry, and does not retain package content after
the process exits. Output reports are written only when the operator chooses an
output path and remain under that operator's control.

## Restrictions

Do not commit real packages or reports to this repository. Use synthetic,
permissioned, or appropriately redacted fixtures for testing. Report a privacy
concern through the process in [SECURITY.md](../../SECURITY.md).
