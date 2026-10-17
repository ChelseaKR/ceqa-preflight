# ADR 0004: The first tag ships the Spanish catalog as a labelled, unreviewed draft

## Status

Accepted — 2026-10-17. Decided by the owner (maintainer).

Supersedes one condition and nothing else: that the qualified Spanish-language
CEQA terminology review,
[#49](https://github.com/ChelseaKR/ceqa-preflight/issues/49), close before the
**first tagged release**. That condition was stated in [I18N.md](../I18N.md)
(release gate, item 3), in the [roadmap](../ROADMAP.md) under "Before first
tagged release" and in its metrics ledger, and in the README. The review itself
is not superseded. It moves to a 1.0 gate. [ADR 0003](0003-explicit-locale-selection-with-no-inference.md)
is unchanged.

## Context

The gettext seam, the English and Spanish catalogs, and the parity gate are
merged ([ADR 0003](0003-explicit-locale-selection-with-no-inference.md)). What
was left of the internationalization release gate is #49: a qualified reviewer
approving the Spanish CEQA terminology and its advisory, non-legal framing. That
review needs a person, and it is still open.

Holding `v0.1.0` on #49 holds back more than Spanish. The composite action
installs its wheel from a GitHub Release and cannot run until one exists. The
pre-commit hook and every install command that names a tag wait on the same
release. English users, for whom the English wording is already authoritative,
wait with them.

Shipping the Spanish catalog unlabelled would be worse than not shipping it.
A reader who is not told that a translation is unreviewed reads it as reviewed,
and the risk #49 exists to catch is a translation that drifts toward implying a
legal determination.

## Decision

1. **`v0.1.0` may be tagged while #49 is open.** It is a pre-release
   development baseline under the 0ver intent of the Release & Versioning
   standard, not a stable release.
2. **The `es` catalog ships labelled as an unreviewed machine draft**, wherever
   the repository's i18n conventions put words in front of a reader:
   - inside every report and comparison, in the active language, appended to
     the disclaimer that the console, HTML, checklist, JSON and SARIF formats
     already carry (JUnit carries no disclaimer and gains none), because a saved or
     shared report travels without the terminal session that made it;
   - on stderr for every non-English run, as before, now naming the 1.0 gate;
   - in the catalog header, the README, [I18N.md](../I18N.md), and the
     composite action's `locale` input description.
   `tests/test_i18n.py` requires the in-report label in Spanish output and its
   absence from English output.
3. **English remains authoritative** in every locale, as before.
4. **#49 becomes a 1.0 gate.** No `1.0.0` tag while it is open, and the
   unreviewed-draft label is removed only when it closes.
5. **Nothing else moves.** The `ai` command prose stays outside the catalog,
   so no Spanish legal-sufficiency refusal is drafted ahead of the review. Every
   other first-tag gate stands: the accessibility review with assistive-technology
   evidence, the residual-risk review, the central applicability registry entry
   (I18N.md item 5), and the rest of the [release checklist](../RELEASE-CHECKLIST.md).

## Consequences

- A Spanish-language reader of `v0.1.0` gets an unreviewed translation, and is
  told so in the report itself and on every run. The English wording governs.
- The release checklist, the roadmap, and I18N.md list #49 under 1.0 rather
  than under the first tag. The I18N standards-conformance row still reads
  "review outstanding".
- Closing #49 now has two visible effects: the 1.0 gate clears, and the label
  is removed, with its test changed to match.
