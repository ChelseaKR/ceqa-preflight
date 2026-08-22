# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and releases
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- Added the real-filing extraction eval and the citation-grounding eval under
  `evals/`, with `scripts/fetch_ceqanet_sample.py` to fetch a small, varied
  sample of real CEQAnet filings (15 committed as identifiers, hashes, and the
  metadata CEQAnet publishes; PDFs stay in a gitignored cache; contact phone,
  email, and address are never written). Recorded the first live results for
  all three suites on Bedrock `claude-sonnet-4-6` (the default `claude-sonnet-5`
  was not reachable): refusal 109/109 end to end with 0 missed; extraction
  88.4% match where both the form and the metadata hold a value, every shown
  value quote-verified; grounding 308/313 claims shown with 0 uncited and 0
  determination-language claims. See `evals/README.md`.
- The quote verifiers now fold typography (curly quotes, dashes, non-breaking
  spaces, ligatures) before verbatim comparison; a quote that differs in a word
  still fails.

- Added `ai explain`, `ai draft-fix`, and `ai ask` (ADR 0002). Explanations and
  correction drafts are grounded in `corpus/`: every claim must cite a passage
  of the official source the rule cites and quote it verbatim, and a verifier
  checks each quote against the corpus and each sentence for determination
  language before display, withholding and counting what fails. `ai ask`
  answers questions about a report's findings behind a deterministic
  legal-sufficiency guard that refuses every phrasing of "is this sufficient /
  will it be accepted / is the exemption valid / did the agency comply" before
  any model call; the model is instructed to refuse as a second layer and the
  verifier is a third. `evals/` now holds the refusal suite (109 refuse
  phrasings, 30 technical questions, English and Spanish), its two-layer
  harness, and the results contract: a recorded result must carry provider,
  model, prompt version, commit, and time, or say `not_run`.

- Added `ceqa-preflight ai extract`, the first command of the opt-in `ai`
  group (ADR 0002). It reads each PDF's text layer through a bounded,
  process-isolated extractor, asks the configured model (Anthropic API or
  Amazon Bedrock via the public `anthropic` SDK; `claude-sonnet-5` by default)
  to copy out manifest facts, and verifies every proposed value against a
  verbatim quote from the document before it is shown. Values whose quote does
  not verify are withheld and counted; fields the text does not state are
  `unknown`; image-only PDFs are reported as having no text layer and never
  sent. The output is a draft manifest for a person to review; `check` is
  unchanged and never invokes it. The provider SDK is an optional extra
  (`ceqa-preflight[ai]`, `[ai-bedrock]`) imported only inside `ai` commands;
  a test proves the default path never imports it. Every output carries
  provenance (provider, model, prompt version, tool version, time).

- Added `make audit-sources` / `scripts/check_rule_sources.py`, a maintainer-run
  link-rot check that confirms every rule catalog source citation URL still
  resolves. It is deliberately excluded from `make verify` and CI: the product
  and its test suite make no real network calls, and this stays a manual,
  periodic companion to the existing rule-source review audits.
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
- Accepted [ADR 0002](docs/adr/0002-ai-at-the-edges.md), an owner-directed
  change of direction: an opt-in `ai` command group will draft manifest fields
  from document text, explain findings against the committed official-source
  corpus, draft corrections, and refuse legal-sufficiency questions. The
  default `check` path is unchanged and still makes no network requests. The
  README, contributing guide, data card, threat model, roadmap, and audit log
  now scope the "no network at runtime" claim to the default path and describe
  the new data flow.

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
- The release workflow now installs with `uv sync --all-groups --locked`
  instead of `--frozen`. `ci.yml` and `security.yml` already made this
  substitution and said why; `release.yml` was the one job left installing a
  lockfile it never compared against `pyproject.toml`, which is the job where
  it matters most.
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
