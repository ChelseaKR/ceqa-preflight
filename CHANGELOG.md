# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and releases
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- Committed artifacts that stand in for a computation are now regenerated and
  compared, instead of standing unchecked. `scripts/check_i18n.py` already
  applied that rule to the gettext catalogs; nothing else did.
  `tests/test_committed_artifacts_are_current.py` extends it to
  `schemas/*.json`, `examples/sample-report.html`,
  `examples/noe-fictional-package/`, three offline corpus invariants,
  `docs/standards/.standards-manifest.json`, and six README figures. Every
  comparison regenerates into a temp directory or an in-memory buffer, so no
  gate can quietly repair the drift it exists to report.

  - `examples/sample-report.html` had drifted, and is regenerated here. Its
    citation links still read "Source" where `reporting.py` now says "Official
    source", "Technical reference", and "Project advisory rule", and the whole
    `source-kind` qualifier note that ships alongside those labels, plus its
    stylesheet rule, was absent. `FILE-004` and `FILE-005` still pointed at the
    repository root rather than the 2026-07-27 source-review addendum. The only
    field excluded from the comparison is `generated_at`; the replacement is
    required to fire exactly once on each side, so a report that stopped
    stating its generation time fails rather than widening what is ignored.
  - `README.md` said the merge gate runs 414 tests. It runs 441. The other five
    figures in that paragraph and the two restated in the standards-conformance
    table were correct and are now pinned to the catalogue, the tracked source
    files, `messages.pot`, and `pyproject.toml`.
  - `tests/test_schema_export.py` exported the schemas into `tmp_path`,
    asserted two `title` strings, and discarded the fresh output without
    looking at the committed bytes. `make schemas` is not part of `verify`, so
    a field added to `PackageManifest` or `InspectionReport` left the published
    contract stale with every check green. Both files match today.
  - `ai/corpus.py` verifies the corpus by walking the manifest, so an orphan
    `corpus/text/*.txt` or `passages.json` key is never visited, and it checks
    only that each passage's text is *contained* in its document, which a
    reordering survives. The manifest, the text directory and the passage keys
    are now required to name the same documents, each document's text must be
    exactly the `\n\n`-join of its passages, `cited_by` may not credit a rule
    the catalogue no longer defines, and the one self-cited document is
    re-derived from the committed markdown it is built from. All four hold
    today and need no network.

- `uv run` without `--locked` performed an implicit sync inside the gates.
  Measured 2026-08-29: with one dependency constraint tightened in
  `pyproject.toml`, `uv run ruff --version` printed `ruff 0.15.22` and changed
  `uv.lock`'s sha from `608be564` to `caef380f`, silently. Every Makefile
  recipe now passes `--locked`, and a new `make lock-check`
  (`uv lock --check --offline`, which resolves and compares but never writes)
  runs first in `make verify`. CI was already protected by
  `uv sync --all-groups --locked`, which is why README.md's claim that CI runs
  the same `make verify` gate needed this to become true locally too.

- The release workflow's changelog check is anchored to a heading.
  `grep -Fq "## [${VERSION}]" CHANGELOG.md` searched the whole file, so a bare
  mention of the string inside the Unreleased body satisfied it and a release
  could be built from a changelog that had never been cut. It now matches
  `^##\s+\[?<version>\]?`, the same shape `tests/test_manifest.py` already
  uses, with the version passed as an argument rather than interpolated into a
  pattern.

- `make verify` no longer fails because of a directory this project does not
  own. `ruff check .` walks the working tree, and the portfolio standards
  repository is cloned into it at `STANDARDS/` by
  `STANDARDS/automation/vendor-standards.sh`, which vendors the documents this
  project ships into `docs/standards/`. Ruff was linting that clone's own
  automation scripts and reporting 16 errors in code from another repository,
  so the headline gate could not be run green by anyone whose working
  directory contained the folder, while every gate underneath it passed.
  `STANDARDS` is added to ruff's `extend-exclude`. That states a scope for the
  linter rather than a claim about what git should track, and it leaves
  `docs/standards/`, which is tracked content, fully linted. `force-exclude`
  is deliberately not set, so a path handed to ruff explicitly is still
  checked. No lint rule, severity, or coverage floor changed.

- Reports can be produced in Spanish. `ceqa-preflight --locale es check …`
  renders console, HTML, and checklist prose, every finding message, and every
  remediation through a gettext catalog; `--locale` is the only input and
  nothing is inferred from the environment, so a report stays reproducible from
  its command line. A well-formed tag with no catalog falls back to English and
  says on stderr which tag could not be met; a malformed tag is a usage error
  rather than a silent downgrade. The Spanish catalog is a maintainer draft
  pending the qualified CEQA terminology review in
  [#49](https://github.com/ChelseaKR/ceqa-preflight/issues/49), and every
  non-English run says so. Rule identifiers, finding status values, JSON field
  names, source citations, and the exit code are the same in every locale.
  Closes items 1, 2, and 4 of the internationalization release gate
  ([#39](https://github.com/ChelseaKR/ceqa-preflight/issues/39)); see
  [ADR 0003](docs/adr/0003-explicit-locale-selection-with-no-inference.md).
- `make verify` gained an `i18n` gate: extraction freshness, byte-exact catalog
  compilation, POT/EN/ES key and placeholder parity, BCP 47 validity, no fuzzy
  or untranslated messages, English-identity, and a check that each compiled
  catalog still says what its source says. The gate is read-only, and each of
  its checks has a test in `tests/test_i18n.py` that proves it goes red.

- The corpus now holds the CEQA Guidelines: every section and appendix of
  14 CCR Title 14, Division 6, Chapter 3 (§ 15000 et seq.), retrieved section
  by section from the official online California Code of Regulations that the
  Office of Administrative Law contracts for, with the site's own currency
  statement recorded as each document's `edition` (OAL publishes no snapshot
  or PDF; this is a dated retrieval of the weekly official edition and may lag
  the live code). Rule packs gained a `guidelines` field that wires the NOD and
  NOE rules to the sections governing their forms, so `ai explain` and
  `ai draft-fix` can quote the regulation verbatim; the rule engine does not
  read it. `scripts/build_corpus.py` walks the official table of contents and
  accepts `--ccr-cache` to reuse a prior crawl.

- Recorded the CCR Guidelines retrieval-compliance review in
  [`docs/audits/ccr-guidelines-retrieval-review-2026-08-21.md`](docs/audits/ccr-guidelines-retrieval-review-2026-08-21.md),
  linked from `corpus/README.md`: OAL publishes no snapshot in any digital
  form (confirmed against its own CCR and historical-versions pages), no
  `robots.txt` disallow or terms language forbidding automated retrieval or
  retention was found on the official online CCR host, and no unofficial
  reprint was substituted. Re-ran the citation-grounding eval live on
  Bedrock `claude-sonnet-4-6` against the Guidelines-wired commit: 20
  previously-withheld claims across the two Guidelines-citing findings
  (`NOE-003`, `NOD-003`) now verify against the retained text;
  `findings_with_nothing_shown` dropped from 7 to 3, and the remaining 3 are
  unrelated to the Guidelines.

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
