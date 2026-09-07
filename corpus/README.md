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

**Retrieval compliance, checked 2026-08-21.** `https://govt.westlaw.com`
serves no `robots.txt` (a request for it 302s to `/SiteList`, the site's
generic catch-all for any unrecognized path — there is no disallow file to
honor). The site's only usage terms are inline on the page: "By using this
website, you agree not to use it in any manner that could disable,
overburden, damage, or impair the site or interfere with any other party's
use of the website, or to use any device, software or routine that
interferes with the proper working of the website." No separate Terms of
Use page is linked (the footer carries only Privacy, Accessibility, and a
link to OAL); nothing in that sentence forbids automated retrieval or
retention, only abuse. `build_corpus.py`'s crawl is one request per second
for about 260 requests, consistent with not overburdening the site.
Separately, OAL's own [Conditions of
Use](https://oal.ca.gov/use/) states that information on its site is "in
the public domain" and "may be distributed or copied as permitted by law,"
consistent with California regulation text being a state edict rather than
copyrighted work. Full findings, including the independent check of OAL's
"no snapshot exists" claim and the historical-versions page, are in
[`docs/audits/ccr-guidelines-retrieval-review-2026-08-21.md`](../docs/audits/ccr-guidelines-retrieval-review-2026-08-21.md).

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

## When a source changes

`make audit-sources` asks whether a citation URL still resolves. That is not
the question a stale citation raises: LCI republishes its checklist and
common-mistakes PDFs each year, the CCR is amended between registers, and a URL
that still returns 200 can be serving text this corpus no longer matches.

    make watch-sources                                       # every document
    uv run python scripts/watch_sources.py --document lci-sch-faq
    uv run python scripts/watch_sources.py --offline-cache DIR   # replay a crawl

The watch re-fetches each document, re-derives its text through the same
extraction `build_corpus.py` used, and writes
`docs/audits/source-watch-YYYY-MM-DD.json`. It is a maintainer tool: it makes
network requests, and it is not part of `make verify`, the CLI, or CI.

**It adopts nothing.** It rebuilds no corpus, edits no rule, and changes
nothing about what `check` reports. The record is evidence for a person to act
on.

### The three verdicts, and why the third is not a fourth kind of "fine"

| Verdict | What it means |
| --- | --- |
| `unchanged` | The re-derived text hashes to the `text_sha256` in `manifest.json`. |
| `changed` | It does not. Every retained passage is then checked for verbatim survival, and the record names the ones lost and the rules bound to the document. |
| `unverifiable` | The source could **not be read**. Nothing is claimed about its content, and no passage is marked lost. |

`unverifiable` carries a `failure_kind`, because the three ways to fail are
evidence about three different things and none of them is evidence about the
law:

- `not_found` — the address answered 404 or 410. A fact about the address.
- `transport` — a timeout, a reset, a DNS failure. A fact about the network.
- `not_checked` — the document was absent from an offline cache. A fact about
  the cache.
- `extraction` — it was fetched, but no passage could be re-derived from the
  response. Almost always an extractor that no longer understands the page, and
  reported as unread rather than as a document that lost every passage.

An `unverifiable` document has `null` in `passages_surviving`, `passages_lost`
and `rules_with_lost_passages` — never `[]`. An empty list of lost passages
reads as a clean bill of health, and a source nobody could read has not earned
one. For the same reason the summary counts `passages_examined` and
`passages_not_examined` separately: adding them together would present unread
passages as passages that survived.

The exit code follows: `0` only when every document was unchanged, `1` when any
document is *not known to be unchanged* — changed **or** unverifiable — and `2`
when the watch could not run at all.

### Adopting a changed source

Nothing is automatic. When the watch reports `changed`:

1. **Read the source.** Open the URL and the record's `passages_lost` together.
   A passage can stop occurring verbatim because the publisher reworded it,
   because a year's edition was reissued, or because the page's markup moved —
   and those are different findings.
2. **Check what stands on it.** `rules_bound` names every rule citing the
   document, and `rules_with_lost_passages` names them when a passage was lost.
   Review each rule's wording against the new text before anything is rebuilt.
3. **Re-retrieve.** `uv run python scripts/build_corpus.py` (see "Rebuilding"
   above). A new citation URL needs a stable identifier in `KNOWN_SOURCE_IDS`
   first; the script refuses to invent one.
4. **Review the diff of `text/` and `passages.json`** like any other source
   change, and re-run the citation-grounding eval, since passage identifiers a
   published eval quoted may no longer exist.
5. **Commit the corpus, the watch record, and the source review together**, so
   a reader can see what changed, when it was noticed, and what was decided.

A `changed` verdict is not by itself a reason to change a rule. It is a reason
for a person to read the source.
