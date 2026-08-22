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

## The CEQA Guidelines (14 CCR § 15000 et seq.)

Every section and appendix of Title 14, Division 6, Chapter 3 of the
California Code of Regulations is a corpus document of its own
(`ccr-14-<section>`, for example `ccr-14-15062`; appendices are
`ccr-14-appendix-<letter>`). The rules that check filing forms are wired to
the sections that govern those forms through the `guidelines` field in the
rule packs (NOE rules to § 15062 and § 15061; NOD rules to § 15075 and
§ 15094; supporting-material prompts to § 15091, § 15093, § 15097), so
`ai explain` and `ai draft-fix` can quote the regulation verbatim. That
wiring is retrieval scope only: the rule engine never reads these texts.

**Edition and provenance.** The Office of Administrative Law publishes no
snapshot or PDF of the CCR. Its official online edition is the
Barclays/Thomson Reuters site that OAL contracts for
(https://govt.westlaw.com/calregs), updated weekly, and OAL states that it
cannot vouch for regulations obtained anywhere else. The text here was
retrieved from that site, section by section; each document's `edition`
field records the site's own currency statement at retrieval (for example
"current through 8/14/26 Register 2026, No. 33") and its `retrieved_at` the
time of retrieval. This is a dated retrieval of the weekly official edition,
not an annual snapshot: it may lag the live code, and a reader who needs the
current regulation should follow the document's URL. The regulation text is
kept; history notes, annotations, and navigation are not.

**Not held as text.** Appendices A (process flow chart), C (Notice of
Completion), D (Notice of Determination), and E (Notice of Exemption) are
published as images in the official edition, with no text layer, so they
are not in the corpus; an explanation that needs the form itself cannot
quote it and will say nothing rather than describe a picture. Repealed
sections whose pages carry no regulation text are likewise omitted.

## Rebuilding

The Guidelines walk is about 260 requests at one per second. To reuse a prior
crawl instead of re-fetching, pass `--ccr-cache DIR` where `DIR` holds the
pages and a `ccr-index.json` listing `title`, `url`, and `file` for each;
`--no-ccr` skips the Guidelines entirely.

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
