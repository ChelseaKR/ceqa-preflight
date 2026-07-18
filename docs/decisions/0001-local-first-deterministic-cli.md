# ADR 0001: Start with a local-first, deterministic CLI

## Status

Accepted on July 18, 2026.

## Context

NOD and NOE packages can contain contact information, project descriptions,
locations, and unpublished materials. Current evidence supports technical
preflight checks, but not a hosted product or legal-analysis system.

## Decision

Version 0.1 will be an installable Python library and command-line interface.
It will process local directories or ZIP archives, write local reports, make
no runtime network calls, and use deterministic checks only.

Version 0.1 will not include:

- A server, database, or account system.
- Cloud storage or telemetry.
- CEQA Submit scraping or an undocumented integration.
- OCR transformations that alter source documents.
- AI or model-based findings.
- Legal sufficiency or accessibility certification.

## Consequences

This lowers privacy, security, procurement, and operational risk. It also
means the initial user interface is less convenient for some planners. A local
browser or desktop shell may be considered only after pilot evidence shows
that the core checks are useful and users need a different interaction model.
