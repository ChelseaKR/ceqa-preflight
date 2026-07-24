# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and releases
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- Tighten the cyclomatic-complexity budget from 15 to 10 and split archive,
  PDF, and pilot analysis into focused, independently testable helpers.
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
