# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and releases
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- Added `make audit-sources` / `scripts/check_rule_sources.py`, a maintainer-run
  link-rot check that confirms every rule catalog source citation URL still
  resolves. It is deliberately excluded from `make verify` and CI: the product
  and its test suite make no real network calls, and this stays a manual,
  periodic companion to the existing rule-source review audits.
- Release publication now authorizes an existing SSH-signed stable tag from
  reviewed `main`, verifies and builds the exact selected commit without a
  shared cache, and hands artifacts to a checkout-free publisher that rechecks
  the immutable tag object.
- Pin the contributor, CI, and release interpreter to Python 3.12 through
  `.python-version`, matching `requires-python` and eliminating ambient runtime
  drift in local setup tools.
- Raise the minimum supported mypy version to 1.18 so strict type checks use
  the portfolio baseline instead of silently accepting older analyzer behavior.
- Tighten the cyclomatic-complexity budget from 15 to 10 and split archive,
  PDF, and pilot analysis into focused, independently testable helpers.
- Correct the internationalization scope from N/A to Applies and document the
  gettext migration boundary, EN/ES review requirements, and public-release
  gate without overstating current conformance.
- Established the local-first CLI foundation, quality gates, governance,
  project boundaries, and source-cited rule catalog.
- Added Portfolio Standards conformance, pinned standards submodule, security
  automation, and release-readiness documentation.
- Added a privacy-preserving, controlled-label evidence kit for the
  permissioned practitioner pilot.
- Gated NOD/NOE-specific filing rules as opt-in experimental rules pending the
  pilot and qualified-practitioner review; documented the current official
  guidance source review.
- Added a pilot partner kit with a non-legal authorization template, private
  reviewer rubric, outreach email, coordinator checklist, and stop conditions.
- Added a `synth` command that generates plainly fictional synthetic packages
  with seedable, objective defects for demos, regression tests, and pilot
  reviewer calibration, plus a committed example package and HTML report.
- Added common rules for flattened form fields (PDF-007), screen-reader
  structure tags (PDF-008), convertible non-PDF documents (FILE-003), advisory
  file size (FILE-004), and portable filenames (FILE-005); narrowed PDF-006 to
  security-relevant active content and taught PDF-003 to recommend OCR for
  scanned documents (rule catalog 1.2.0).
- Sped up inspection: one text-extraction parse per PDF instead of one per
  sampled page, and bounded concurrent per-PDF worker processes with
  content-free progress events.
- Extended the CLI: batch `check` over multiple packages with a roll-up
  summary, `--rules`/`--exclude-rules` selection, a printable
  `--format checklist` sign-off report, `init --from-package` manifest
  prepopulation, `rules list --format json`, and report summaries with a
  print-friendly HTML stylesheet.
