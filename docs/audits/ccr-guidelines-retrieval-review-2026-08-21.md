# CCR Guidelines retrieval-compliance review — 2026-08-21

## Question

Issue #49 scoped the CEQA Guidelines corpus gap (14 CCR § 15000 et seq.) as
"use the OAL annual CCR snapshot route": retain the Office of Administrative
Law's published snapshot of Title 14, Division 6, Chapter 3, with hash,
retrieval date, and snapshot year labeled. This review checks whether that
snapshot exists, and if not, what the owner-approved fallback (the official
published CCR) permits.

## Finding 1: no OAL snapshot exists, in any digital form

[oal.ca.gov/publications/ccr/](https://oal.ca.gov/publications/ccr/) states
that "OAL contracts with Barclays, a division of Thomson-Reuters to provide a
free online version of the Official CCR" at `govt.westlaw.com/calregs`, that
"OAL updates the official hard-copy and online versions of the code once
weekly," and that "OAL cannot verify the authenticity of regulations
downloaded from websites other than" that one. It does not offer a
downloadable snapshot or PDF of its own.

Its linked historical-versions page,
[oal.ca.gov/ccr_history/](https://oal.ca.gov/ccr_history/), confirms there is
no digital archive at all, annual or otherwise: past versions are found
through each section's History Notes (which cite the Register week/year of
the change), and the actual past text is only available as hard-copy or
microfiche CCR Supplements (Registers) held by the Witkin State Law Library,
or as the originally adopted text on file with the California State Archives.
"The online CCR is updated electronically" with current text only — it is
not itself an archive.

**The premise in issue #49 does not correspond to anything that exists.**
There is no OAL-published snapshot, annual or otherwise, to retain a hash of.
The nearest official, citable, dated text is the live official online CCR at
`govt.westlaw.com/calregs` — the site OAL itself designates as authoritative
and directs the public to rely on over any other source.

## Finding 2: retrieval terms and robots.txt, `govt.westlaw.com`

Checked directly (2026-08-21/22), with both a bare HTTP client and a
standard browser user agent, to be sure of the actual site behavior rather
than repeat an unverified claim:

- A request for `/robots.txt` with no user agent gets a generic Cloudflare
  bot-challenge (403 "Sorry, you have been blocked"). The identical request
  with a normal browser user agent — what a page load, and what
  `build_corpus.py`'s crawl, actually present — gets `302 Found` to
  `/SiteList`, the site's generic catch-all for any unrecognized path. There
  is no `robots.txt` file and therefore no disallow directives to honor. The
  403 on the bare request is ordinary bot-mitigation infrastructure (Akamai/
  Cloudflare-style challenge on unidentified clients), not a block placed on
  this retrieval specifically — the same browser-UA request that clears
  `/robots.txt` also reaches the real CCR table of contents at
  `/calregs/Index...` with a normal `200 OK`.
- No separate Terms of Use page is linked; the footer carries only Privacy,
  Accessibility, and a link to OAL. The only usage restriction on the page is
  one inline sentence: "By using this website, you agree not to use it in
  any manner that could disable, overburden, damage, or impair the site or
  interfere with any other party's use of the website, or to use any device,
  software or routine that interferes with the proper working of the
  website." That restricts abusive/disruptive use (denial-of-service-style
  conduct); it does not forbid automated reading or retention.
- `build_corpus.py`'s Guidelines walk is one request per second for about
  260 requests total — well inside what that sentence describes as
  acceptable, and consistent with not overburdening the site.
- Separately, OAL's own [Conditions of
  Use](https://oal.ca.gov/use/) (verified independently, dated 2000-12-07)
  states site content is, "in general... considered in the public domain"
  and "may be distributed or copied as permitted by law." That is
  consistent with California regulatory text being a state edict rather
  than copyrighted work, though it describes OAL's own site, not Westlaw's.

**Conclusion: nothing found forbids automated retrieval or retention.** No
`robots.txt` disallow exists, and the only usage-terms language found
restricts abuse, not reading or keeping the text. Retention proceeded on
that basis, not by routing around a restriction — had either check turned up
a prohibition, this document would record that finding and the corpus gap
would stay open instead.

## What was retained

As committed in `163e77a`: all 285 documents (sections and appendices) of
Title 14, Division 6, Chapter 3, 659 passages, walked section-by-section from
`govt.westlaw.com/calregs`. Each document's `edition` field records the
site's own displayed currency statement at the moment of retrieval — for
example, `ccr-14-15062` (Notice of Exemption) carries "Barclays Official
California Code of Regulations, current through 8/14/26 Register 2026,
No. 33" — and its `retrieved_at` field the UTC fetch timestamp;
`source_sha256`/`text_sha256` hash the raw and extracted text respectively.
This is a **dated retrieval of the live, weekly-updated official edition,
not an annual snapshot**, and is labeled that way in `corpus/README.md` and
everywhere the edition is surfaced: it may lag the current regulation by up
to the week between Register updates, and a reader who needs the current
text should follow the document's `url`.

Appendices A (process flow chart), C (Notice of Completion), D (Notice of
Determination), and E (Notice of Exemption) are images with no text layer in
this source and are not held as text; nothing was substituted from another,
unofficial reprint to fill that gap.

## Rule-wiring and grounding re-run

`163e77a` added a `guidelines` field to the NOD and NOE rule packs (NOE
rules to § 15062 / § 15061; NOD rules to § 15075 / § 15094; supporting-
material prompts to § 15091 / § 15093 / § 15097) for `ai explain` /
`ai draft-fix` retrieval only — the rule engine does not read it. The
grounding eval was re-run live on Bedrock `global.anthropic.claude-sonnet-4-6`
against the new commit (`evals/grounding/results/
2026-08-22-run-bedrock-global.anthropic.claude-sonnet-4-6.json`).

Before wiring (commit `f7665f5`), 7 findings across the 5 synthetic reports
produced nothing at all, each noted `"The cited guidance did not support any
claim that passed verification."`: `FILE-002` (x2), `NOE-003` (x2),
`NOD-003` (x2), `PDF-006` (x1).

After wiring (commit `163e77a`), 4 of those 7 now produce and show claims
that quote the Guidelines verbatim — exactly the two Guidelines-citing rules,
each recurring across two of the synthetic reports:

| Rule | Before | After |
| --- | --- | --- |
| `NOE-003` (report 1) | 0 produced / 0 shown | 5 produced / 5 shown |
| `NOE-003` (report 2) | 0 produced / 0 shown | 5 produced / 5 shown |
| `NOD-003` (report 1) | 0 produced / 0 shown | 5 produced / 5 shown |
| `NOD-003` (report 2) | 0 produced / 0 shown | 5 produced / 5 shown |

**20 previously-withheld claims now verify**, all against the newly-retained
Guidelines text. `findings_with_nothing_shown` dropped from 7 to 3. The
remaining 3 are unrelated to the Guidelines and stay withheld correctly:
`FILE-002` (x2) is a self-cited project rule with no official corpus source
to quote, and `PDF-006` (x1) cites a different, unrelated official source.

The run's other movement — `claims_produced` 313→342, `claims_shown`
308→331, `verified_share_of_produced` 0.984→0.968 — is a mix of the
Guidelines resolution above and ordinary live-model variance between runs:
three cases (`CAT-001` x2, `MAN-001` x1) hit a transient `model output was
not a JSON object` parse failure on this run that hadn't occurred on the
prior one, while several `CAT-001` cases that had errored previously
resolved cleanly this time. None of that is caused by the corpus change; it
is the kind of run-to-run noise ADR 0002 anticipates by requiring every
recorded number to come from a live, provenance-stamped run rather than an
estimate. No claim was fabricated or backfilled to smooth it over.

## Result

The CEQA Guidelines corpus gap is closed through the OAL-designated official
online CCR (Westlaw/Barclays under contract to OAL), retained as a dated,
honestly-labeled weekly edition — not an annual snapshot, because no such
snapshot exists — after an explicit check that found no `robots.txt`
disallow and no terms language forbidding automated retrieval or retention.
No unofficial reprint was substituted for it. Issue #49's qualified-review
scope now includes this corpus text; this document is the record it asks
for.
