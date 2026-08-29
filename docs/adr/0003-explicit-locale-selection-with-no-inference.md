# ADR 0003: Locale is selected explicitly, never inferred, and English is a catalog

## Status

Accepted — 2026-08-27.

Implements the release gate declared in [I18N.md](../I18N.md) and tracked as
[#39](https://github.com/ChelseaKR/ceqa-preflight/issues/39). Does not amend
[ADR 0001](../decisions/0001-local-first-deterministic-cli.md) or
[ADR 0002](0002-ai-at-the-edges.md); the default `check` path keeps every
guarantee both records make.

## Context

CEQA Preflight writes advisory reports for a California civic process in which
a large share of the public, and of the staff serving them, works in Spanish.
Until now every user-visible string was embedded in source, English-only. That
was recorded honestly as a pre-release gap rather than an N/A control, and it
is the largest single item standing between the current state and a first
tagged release.

Three decisions inside "add gettext" are not obvious, and each one has a
failure mode that would be worse than staying English-only.

**How the locale is chosen.** The conventional answer is to read `LANG` and
friends. That would make the same command produce different reports on two
machines, which breaks the property this tool sells: a report reproducible from
its inputs. It would also mean a filer could hand a colleague a command line
that quietly renders differently for them.

**What happens when a language is asked for and not shipped.** The gettext
default is `fallback=True`, which returns the untranslated message. That is the
worst available behavior here: `--locale fr` would be accepted, raise nothing,
and produce a report in English that the reader believes is French.

**Whether English needs a catalog.** With English as the `msgid`, English works
with no catalog at all. Shipping one looks like pure redundancy.

## Decision

**Locale is explicit at the command-line boundary.** `--locale` is the only
input. No environment variable, network response, IP address, or document
content is consulted. Omitting the flag is an English run, every time.

**Every outcome is stated.** A well-formed tag with no catalog falls back to
English *and says so on stderr, naming the tag*. A malformed tag is a usage
error with exit code 2, because a typo is the user's to fix, not something to
silently downgrade. Loading a catalog uses `fallback=False`, so a missing or
corrupt `.mo` raises instead of rendering English under another language's
name.

**English is a catalog like any other**, and `scripts/check_i18n.py` requires
every English `msgstr` to be byte-identical to its `msgid`. This buys two
things a bare fallback cannot. English and Spanish become peers that a parity
gate can compare, and English prose acquires a tripwire: an edit to the English
catalog that changes wording fails the build instead of silently changing what
the tool says.

**Translation is prose only.** Rule identifiers, rule versions, finding status
values, JSON field names, command and option names, source citations, and the
exit code are stable identifiers and never enter a catalog. `tests/test_i18n.py`
renders the same package in both locales and asserts that every non-prose value
in the JSON report is identical, and that the exit code matches.

**A command restores the locale it changed.** The CLI puts the previous catalog
back when the command closes, so one process running several commands cannot
leak a language from one into the next.

## Consequences

Spanish speakers can read the advisory report. Release-gate items 1, 2, and 4
close; item 3, the qualified terminology review, is a person and stays open,
and the shipped Spanish catalog says so in its header, on every non-English
run, and in the README.

`make verify` gains nine checks over the catalogs, each with a test that proves
it can fail. The compiled `.mo` files are committed, which means catalogs must
be recompiled with `make i18n-update` when a `.po` changes; the gate catches it
when they are not. Byte-comparing compiled catalogs requires every `.po` to pin
a complete header including `POT-Creation-Date`, because Babel otherwise fills
that field from the wall clock and the gate would fail on a clean tree.

The cost is a second place to edit prose. Wording changes now touch source and
two catalogs, and the build refuses the change until all three agree. That is
the intended trade: the alternative is a translation that drifts quietly, which
in an advisory civic tool is the failure that matters.

Rule catalog titles, source citation titles, pilot evidence reasons, CLI help,
and the opt-in `ai` prose are outside the seam for reasons recorded in
[I18N.md](../I18N.md). The `ai` exclusion is the one worth restating: that
module holds the legal-sufficiency refusal, and drafting an unreviewed Spanish
refusal would put the riskiest sentence in the tool into a catalog ahead of the
review that governs it.
