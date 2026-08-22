# Corpus: the official source text the AI layer may quote

This directory is the only text the opt-in `ai explain` and `ai draft-fix`
commands ([ADR 0002](../docs/adr/0002-ai-at-the-edges.md)) are allowed to
quote. Every explanation claim must cite a passage identifier from
`passages.json` and quote it verbatim; the verifier checks the quote against
the passage before anything is displayed, and a claim that does not verify is
withheld.

## Contents

| File | What it is |
| --- | --- |
| `manifest.json` | One entry per source: stable `id`, title, URL, `kind`, retrieval time, content type, SHA-256 of the bytes fetched, SHA-256 of the extracted text, passage count, and the rule identifiers that cite it. |
| `text/<id>.txt` | The extracted plain text of each source, whitespace-normalized, one passage per blank-line-separated block. |
| `passages.json` | The same text split into addressable passages (`<id>#pNNN`) under their nearest heading. |

`kind` says what authority the source carries, and the HTML report labels
citations the same way:

- `official` — State of California guidance (LCI State Clearinghouse pages and
  PDFs).
- `technical_reference` — a non-CEQA technical reference (OWASP, cited by the
  active-content security rule).
- `project_advisory` — this project's own documented reasoning. `FILE-004`
  and `FILE-005` cite the
  [2026-07-27 source review addendum](../docs/audits/rule-source-review-2026-07-27-addendum.md)
  because no official source states a file-size limit or a filename character
  set. An explanation of those rules says so rather than presenting the
  threshold as official.

## Attribution

LCI State Clearinghouse pages and PDFs are State of California publications
reproduced here as plain text for verification only; they are not altered.
The OWASP "Unrestricted File Upload" page is © OWASP Foundation and licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); its text is
reproduced under that license with this attribution.

## What is deliberately not here

The text of the CEQA statute and Guidelines (for example Guidelines
§ 15062 on Notice of Exemption contents, § 15075 and § 15094 on Notice of
Determination contents). The official publisher of the California Code of
Regulations is Westlaw under contract with the Office of Administrative Law,
and LCI's own site refers readers to a professional association's reprint.
Neither is a source the maintainer has reviewed for this corpus. Until an
official, reviewable text is added, explanations do not cite the Guidelines
and say so when a user asks about them.

## Rebuilding

    uv run python scripts/build_corpus.py

The script fetches every unique citation URL in the built-in rule catalog
plus the documents it lists under `EXTRA_SOURCES`, and reads self-cited
project documents from the working tree. It is a maintainer tool: it makes
network requests, so it is not part of `make verify`, the CLI, or CI. Rebuild
it when a rule-source review finds that official guidance changed, review
the diff of `text/` like any other source change, and commit it together
with the updated review. A new citation URL must first be given a stable
identifier in `KNOWN_SOURCE_IDS`; the script refuses to invent one.

`Corpus.load()` verifies every text file against the manifest hash and every
passage against its document text, so an edited corpus fails to load rather
than passing as the official source.
