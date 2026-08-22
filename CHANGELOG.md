# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and releases
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- Added `corpus/`, the committed, hashed, dated plain text of every official
  source the rule catalog cites (plus the LCI document-submission page and the
  project's own source-review addendum), split into addressable passages, with
  `scripts/build_corpus.py` to rebuild it and a loader that refuses text that
  does not match its manifest. It is the only text the opt-in AI explanation
  layer (ADR 0002) may quote. The corpus ships inside the wheel.
- Source citations now carry a `kind` (`official`, `technical_reference`, or
  `project_advisory`) and the HTML report labels each citation link with it
  instead of a bare "Source". `FILE-004` and `FILE-005`, which are self-cited
  because no official guidance states a file-size limit or a filename character
  set, now link to the 2026-07-27 source-review addendum that explains their
  thresholds rather than to the repository root, and are labeled "Project
  advisory rule — not an official source" (closes #38). Report schema `1.1`
  gains the optional `source.kind` field; existing consumers are unaffected.

- Every report now names the checks that did not run. A rule that applies to the
  filing type but was skipped — experimental without `--include-experimental`,
  removed by `--rules` or `--exclude-rules`, or withdrawn — is listed with its
  identifier, source citation, and the reason, in the console, JSON, HTML, and
  checklist formats. Previously a default NOE or NOD run silently omitted the six
  filing-specific rules (six of the twenty that apply), two of which can produce a
  failure, and `--exclude-rules` could turn a report with warnings into `0
  failure(s), 0 warning(s)` with no trace of the removal; the printable sign-off
  checklist, whose next step is submission, was identical either way. Exit codes
  are unchanged: a skipped check still exits `0`, which the README now states
  explicitly.
- Report schema version `1.1` adds the `not_run` array. The addition is
  backwards compatible; existing consumers of `findings` and `manual_review` are
  unaffected.
- Fixed checks that reported a clean result for documents they never read. A PDF
  that timed out, failed to parse, or is encrypted still produced a
  `PdfInspection` with every absence signal at its default, so the searchable
  text, active content, fillable form, and structure tag checks passed on it.
  A package whose PDFs all timed out therefore produced the same passing lines
  as a package that was genuinely clean. Those checks now examine only
  completed inspections, state the number of documents each pass covers, and
  report anything they could not examine as a manual-review item.
- `PdfInspection` now carries `form_fields_readable`, so a form dictionary that
  could not be parsed is distinguishable from a document with no form fields
  rather than both reporting a field count of zero.
- CI and the security workflow install with `uv sync --locked` instead of
  `--frozen`; `--frozen` exits 0 on a lockfile that has drifted from
  `pyproject.toml`, so lockfile drift previously passed unnoticed.
- Enabled `pytest-socket` through `--disable-socket`. It was a declared
  development dependency that was never activated, so nothing enforced the
  documented "no network requests at runtime" boundary; a test now fails if the
  guard is ever switched off.
- Corrected workflow and script comments that described this public repository
  as private.
- Named every portfolio standard explicitly in the README conformance table
  with reasoned N/A rows, added a Quality & Metrics ledger and
  AI-development-measurement declaration to the roadmap, and disclosed
  AI-assisted development in the README.
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
