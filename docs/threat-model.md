# Threat model

## Assets

- Unsubmitted filing packages and their metadata.
- User filesystem integrity and available disk/CPU resources.
- Report integrity, including source citations and finding order.

## Trust boundaries

1. A directory or ZIP supplied by the user is untrusted input.
2. PDFs inside that package are untrusted input.
3. Built-in YAML rule packs and registered Python checks are trusted project
   code, reviewed through version control and CI.
4. Reports are written only to an explicit user-selected output directory.

## Controls

- ZIP traversal, symlinks, duplicate paths, non-regular files, compression
  bombs, excessive counts, and size limits are rejected before inspection.
- PDFs are read in a spawned worker with a hard timeout. The inspector does
  not invoke OCR, a shell, an external executable, or a network service.
- Rule metadata is parsed with `safe_load`, requires source citations and a
  strict registry name, and rejects executable-looking parameters. Rules may
  not dynamically execute configuration.
- The tool hashes inputs for a local report fingerprint but does not log page
  text or transmit data on the default path.
- The opt-in `ai` commands ([ADR 0002](adr/0002-ai-at-the-edges.md)) transmit
  bounded document text or report findings to the configured model provider
  over HTTPS using a credential read from the environment. They are never
  invoked by `check`, import the provider SDK lazily, and treat every model
  response as untrusted: extracted values must quote the document and are
  verified against it; explanation claims must quote the committed corpus and
  are verified against it; a deterministic guard refuses legal-sufficiency
  questions before and after the model call. No model output becomes a
  finding.

## Residual risks

Local parsing libraries can still contain defects. Treat the tool as a
workstation utility, run it with ordinary-user permissions, keep dependencies
updated, and do not rely on it as a malware scanner, accessibility certifier,
or legal compliance system.
