"""Validate the shipped gettext catalogs before they can reach a report.

`docs/I18N.md` promises four things of `make verify`: that catalogs compile, that EN and
ES are at key and placeholder parity, that every shipped locale tag is valid BCP 47, and
that extraction is fresh. All four live here, along with three invariants the standard
implies but does not name:

* English is a catalog, not an implicit fallback, so every English msgstr must be
  byte-identical to its msgid. Without this, English report prose could drift away from
  the source strings the test suite pins, silently and invisibly.
* A compiled catalog must agree with the `.po` it came from. A stale `.mo` is the exact
  shape of the worst i18n bug: `--locale es` is accepted, no error is raised, and the
  reader gets English while believing they asked for Spanish.
* A *non*-source msgstr must not be verbatim English. Measured 2026-09-07: before this
  check existed, `make i18n` stayed green on a Spanish `msgstr` set character for
  character to its English `msgid`. Parity, completeness and placeholder checks are all
  satisfied by that string -- it is non-empty, its key matches, and its placeholders are
  trivially identical -- and the English identity row above only ever looks at `en`. So
  the reader got English, from a catalog reporting 100% translated, with the gate green.
  See `_translation_identity_failures` for what is exempt and why.

Extraction and compilation are regenerated in memory and compared byte for byte, so the
gate writes nothing: running `make verify` can never quietly repair the drift it exists to
report. Doing it in Python rather than shelling out to `pybabel` and `cmp` also keeps the
gate working on Windows, where a POSIX scratch path is not a path the interpreter can
write to. That is not hypothetical; it is how the first version of this gate failed.
"""

from __future__ import annotations

import gettext
import io
import re
import sys
from collections import Counter
from pathlib import Path

from babel import Locale, UnknownLocaleError
from babel.messages import frontend, mofile, pofile
from babel.messages.catalog import Catalog
from babel.messages.extract import extract_from_dir

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
MAPPING = ROOT / "babel.cfg"
LOCALES = ROOT / "src" / "ceqa_preflight" / "locales"
TEMPLATE = LOCALES / "messages.pot"
DOMAIN = "messages"
# Kept in step with ceqa_preflight.i18n.SUPPORTED_LOCALES by test_i18n.py, so this script
# stays runnable without importing the package it is checking.
EXPECTED_LOCALES = ("en", "es")
SOURCE_LOCALE = "en"

# `[A-Za-z_]` and `[0-9]` are written out rather than using `\w`/`\d`, which in Python
# match far more than ASCII and would treat a fullwidth digit as a placeholder name.
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: A whole message that is nothing but a web address.
URL_ONLY = re.compile(r"https?://\S+")
#: One letter in any script. `\w` would also match digits and `_`.
LETTER = re.compile(r"[^\W\d_]")

#: Messages a translator may leave identical to their English source, each mapped to the
#: reason it is the same in both languages.
#:
#: **This is deliberately empty, and that is a measurement, not an oversight.** Every
#: shipped `es` message differs from its `msgid`, so the identity check below costs
#: nothing to satisfy and no exemption has yet had to be argued for. Deliberately not a
#: count: a number here would be one more hand-maintained figure to keep in step, and
#: `make i18n` proves the property itself on every run.
#:
#: An entry here is a claim about a string, so it carries the reason as a value rather
#: than living in a bare list. Adding one is meant to be a small, deliberate, reviewable
#: act -- the way a spell-checker's dictionary grows -- because the alternative designs
#: are both worse. A blanket must-differ rule with no exemption mechanism would go red the
#: first time someone wraps `CSV`, and a gate that cannot be satisfied is a gate that gets
#: deleted. A content heuristic that exempts short all-caps tokens would swallow `CSV` and
#: `SARIF` and also `NEW`, `SAME` and `GONE` -- three real messages this catalog
#: translates today (`NUEVO`, `IGUAL`, `YA NO APARECE`). No predicate can tell those two
#: groups apart, because there is nothing in the strings to tell apart. Only a person
#: knows which is which, so a person writes it down.
#:
#: `_allowlist_failures` fails on an entry that is no longer earning its place, so this
#: cannot silently become the drawer an untranslated string is swept into.
IDENTICAL_BY_DESIGN: dict[str, str] = {}


def _read(path: Path, locale: str | None = None) -> dict[str, str]:
    with path.open(encoding="utf-8") as stream:
        catalog = pofile.read_po(stream, locale=locale)
    messages: dict[str, str] = {}
    for message in catalog:
        if not message.id or not isinstance(message.id, str):
            continue
        if not isinstance(message.string, str):
            raise TypeError(f"{path}: plural messages are not supported yet ({message.id!r})")
        messages[message.id] = message.string
    return messages


def _flag_failures(path: Path, locale: str) -> list[str]:
    failures: list[str] = []
    with path.open(encoding="utf-8") as stream:
        catalog = pofile.read_po(stream, locale=locale)
    for message in catalog:
        if not message.id or not isinstance(message.id, str):
            continue
        if "fuzzy" in message.flags:
            failures.append(f"{locale}: fuzzy message {message.id[:60]!r}")
        if not message.string:
            failures.append(f"{locale}: untranslated message {message.id[:60]!r}")
    return failures


def _locale_directories() -> list[str]:
    return sorted(
        entry.name
        for entry in LOCALES.iterdir()
        if entry.is_dir() and (entry / "LC_MESSAGES" / f"{DOMAIN}.po").is_file()
    )


def _shipped_locale_failures(shipped: list[str]) -> list[str]:
    failures: list[str] = []
    if shipped != sorted(EXPECTED_LOCALES):
        failures.append(
            f"shipped catalogs {shipped} do not match expected {sorted(EXPECTED_LOCALES)}"
        )
    for tag in shipped:
        try:
            Locale.parse(tag, sep="-")
        except (ValueError, UnknownLocaleError, TypeError):
            failures.append(f"{tag!r} is not a valid BCP 47 locale directory name")
            continue
        declared = _declared_language(LOCALES / tag / "LC_MESSAGES" / f"{DOMAIN}.po")
        if declared != tag:
            failures.append(f"{tag}: catalog declares Language: {declared!r}, not {tag!r}")
    return failures


def _declared_language(path: Path) -> str | None:
    with path.open(encoding="utf-8") as stream:
        catalog = pofile.read_po(stream)
    for key, value in catalog.mime_headers:
        if key.lower() == "language":
            return value.strip()
    return None


def _parity_failures(catalogs: dict[str, dict[str, str]], template: set[str]) -> list[str]:
    failures: list[str] = []
    if not template:
        failures.append("the extraction template is empty, so nothing would be translated")
    for locale, messages in catalogs.items():
        only_in_template = template - messages.keys()
        only_in_catalog = messages.keys() - template
        for message in sorted(only_in_template)[:5]:
            failures.append(f"{locale}: missing message from the template: {message[:60]!r}")
        for message in sorted(only_in_catalog)[:5]:
            failures.append(f"{locale}: message not in the template: {message[:60]!r}")
    return failures


def _placeholder_failures(catalogs: dict[str, dict[str, str]]) -> list[str]:
    """Compare placeholder multisets, not sequences.

    A translation is allowed to reorder placeholders, because word order is exactly what
    changes between languages. Dropping one, inventing one, or repeating one a different
    number of times is not allowed: the first would blank a value in a report and the
    second would raise `KeyError` at format time, in front of a user.
    """

    failures: list[str] = []
    for locale, messages in catalogs.items():
        for message, translation in messages.items():
            if Counter(PLACEHOLDER.findall(message)) != Counter(PLACEHOLDER.findall(translation)):
                failures.append(f"{locale}: placeholder mismatch in {message[:60]!r}")
    return failures


def _source_identity_failures(catalog: dict[str, str]) -> list[str]:
    return [
        f"{SOURCE_LOCALE}: msgstr differs from msgid for {message[:60]!r}"
        for message, translation in catalog.items()
        if message != translation
    ]


def _carries_translatable_text(message: str) -> bool:
    """Is there anything in ``message`` a translator could have changed?

    Two shapes structurally cannot hide an untranslated English word, so they need no
    entry in :data:`IDENTICAL_BY_DESIGN` and raise no finding when they are identical:

    * nothing but placeholders, digits, punctuation and symbols -- ``{path}``, ``1.2``,
      ``--`` -- because after the placeholders are removed no letter is left to translate;
    * a bare web address, which is an identifier rather than prose.

    Both tests are about *letters*, not about length or case, and that is the point. It is
    tempting to also exempt short all-caps tokens so `CSV` and `SARIF` pass unremarked --
    and that heuristic would exempt `NEW`, `SAME` and `GONE`, which this catalog really
    does translate. Anything with a letter in it therefore needs a person to say so.
    """

    without_placeholders = PLACEHOLDER.sub(" ", message).strip()
    if URL_ONLY.fullmatch(without_placeholders):
        return False
    return bool(LETTER.search(without_placeholders))


def _translation_identity_failures(locale: str, messages: dict[str, str]) -> list[str]:
    """Fail when a translated catalog ships the English string as its translation.

    This is the gap the three checks above cannot see between them. A verbatim-English
    Spanish `msgstr` is non-empty, so completeness passes; its key is in the template, so
    parity passes; its placeholders are the same characters, so placeholder parity passes.
    `_source_identity_failures` asserts the *English* catalog matches its source and says
    nothing about any other, which is correct for what it is checking and is why nothing
    was left watching this.
    """

    identical = [
        message
        for message, translation in messages.items()
        if message == translation
        and _carries_translatable_text(message)
        and message not in IDENTICAL_BY_DESIGN
    ]
    failures = [
        f"{locale}: msgstr is verbatim English for {message[:60]!r}; translate it, or "
        f"record it in IDENTICAL_BY_DESIGN in {Path(__file__).name} with the reason it "
        "is the same in both languages"
        for message in sorted(identical)[:5]
    ]
    if len(identical) > 5:
        failures.append(f"{locale}: {len(identical)} message(s) are verbatim English in total")
    return failures


def _allowlist_failures(catalogs: dict[str, dict[str, str]]) -> list[str]:
    """Fail on an exemption that is no longer earning its place.

    Without this the allowlist is a one-way door: a string exempted once stays exempt
    after it is renamed, deleted, or actually translated, and the drawer it opens is
    exactly where a future untranslated message would come to rest. An exemption is live
    only while some shipped non-source catalog still leaves that message identical.
    """

    translated = {
        locale: messages for locale, messages in catalogs.items() if locale != SOURCE_LOCALE
    }
    failures = []
    for message, reason in IDENTICAL_BY_DESIGN.items():
        if not reason.strip():
            failures.append(
                f"IDENTICAL_BY_DESIGN records no reason for {message[:60]!r}; the reason "
                "is the entry's whole justification"
            )
        if not any(message in messages for messages in translated.values()):
            failures.append(
                f"IDENTICAL_BY_DESIGN names {message[:60]!r}, which no translated catalog "
                "holds; remove the entry"
            )
        elif not any(messages.get(message) == message for messages in translated.values()):
            failures.append(
                f"IDENTICAL_BY_DESIGN exempts {message[:60]!r}, but every translated "
                "catalog now translates it; remove the entry"
            )
    return failures


def _compiled_failures(catalogs: dict[str, dict[str, str]]) -> list[str]:
    """Prove the compiled catalog a run actually loads says what the `.po` says.

    Two comparisons, because they fail differently. The semantic one names the message
    that drifted, which is what a person needs in order to fix it. The byte one catches
    anything the semantic one cannot see, such as a header that stopped matching.
    """

    failures: list[str] = []
    for locale, messages in catalogs.items():
        compiled = LOCALES / locale / "LC_MESSAGES" / f"{DOMAIN}.mo"
        if not compiled.is_file():
            failures.append(f"{locale}: no compiled catalog; run `make i18n-update`")
            continue
        with compiled.open("rb") as stream:
            translations = gettext.GNUTranslations(stream)
        stale = [
            message
            for message, translation in messages.items()
            if translations.gettext(message) != translation
        ]
        for message in sorted(stale)[:5]:
            failures.append(f"{locale}: compiled catalog is stale for {message[:60]!r}")
        if stale:
            failures.append(
                f"{locale}: {len(stale)} stale compiled message(s); run `make i18n-update`"
            )
        elif compiled.read_bytes() != _compile(locale):
            failures.append(
                f"{locale}: compiled catalog does not match its source; run `make i18n-update`"
            )
    return failures


def _compile(locale: str) -> bytes:
    """Compile one catalog in memory, exactly as `pybabel compile` would write it."""

    path = LOCALES / locale / "LC_MESSAGES" / f"{DOMAIN}.po"
    with path.open(encoding="utf-8") as stream:
        catalog = pofile.read_po(stream, locale=locale)
    buffer = io.BytesIO()
    mofile.write_mo(buffer, catalog)
    return buffer.getvalue()


def _extract() -> bytes:
    """Re-extract the template in memory, exactly as `pybabel extract` would write it."""

    with MAPPING.open(encoding="utf-8") as stream:
        method_map, options_map = frontend.parse_mapping_cfg(stream)
    catalog = Catalog()
    for filename, lineno, message, comments, context in extract_from_dir(
        str(SOURCE), method_map=method_map, options_map=options_map
    ):
        catalog.add(message, None, [(filename, lineno)], auto_comments=comments, context=context)
    buffer = io.BytesIO()
    pofile.write_po(buffer, catalog, no_location=True, omit_header=True)
    return buffer.getvalue()


def _normalize_newlines(data: bytes) -> bytes:
    """Compare catalog content, not the line endings a checkout happened to use.

    `.gitattributes` pins `.pot` and `.po` to LF so this rarely matters, but a contributor
    with a CRLF working tree should get a real finding or none, never a phantom one: Babel
    always writes LF, and a line ending is not something a translator authored.
    """

    return data.replace(b"\r\n", b"\n")


def _extraction_failures(template: set[str]) -> list[str]:
    """Fail when a wrapped string never reached the template, or a stale one lingers."""

    regenerated = _extract()
    if _normalize_newlines(regenerated) == _normalize_newlines(TEMPLATE.read_bytes()):
        return []
    with io.StringIO(regenerated.decode("utf-8")) as stream:
        fresh = {
            message.id
            for message in pofile.read_po(stream)
            if message.id and isinstance(message.id, str)
        }
    failures = [
        f"template is stale: {message[:60]!r} is wrapped in source but not extracted"
        for message in sorted(fresh - template)[:5]
    ]
    failures += [
        f"template is stale: {message[:60]!r} is extracted but no longer in source"
        for message in sorted(template - fresh)[:5]
    ]
    if not failures:
        failures.append("template differs from a fresh extraction but carries the same messages")
    failures.append("run `make i18n-update`")
    return failures


def main() -> int:
    """Fail if any catalog would mislead a reader about the language it is in."""

    failures: list[str] = []
    shipped = _locale_directories()
    failures.extend(_shipped_locale_failures(shipped))

    template = set(_read(TEMPLATE))
    failures.extend(_extraction_failures(template))
    catalogs = {
        locale: _read(LOCALES / locale / "LC_MESSAGES" / f"{DOMAIN}.po", locale)
        for locale in shipped
    }
    for locale in shipped:
        failures.extend(_flag_failures(LOCALES / locale / "LC_MESSAGES" / f"{DOMAIN}.po", locale))
    failures.extend(_parity_failures(catalogs, template))
    failures.extend(_placeholder_failures(catalogs))
    if SOURCE_LOCALE in catalogs:
        failures.extend(_source_identity_failures(catalogs[SOURCE_LOCALE]))
    for locale, messages in catalogs.items():
        if locale != SOURCE_LOCALE:
            failures.extend(_translation_identity_failures(locale, messages))
    failures.extend(_allowlist_failures(catalogs))
    failures.extend(_compiled_failures(catalogs))

    if failures:
        print("i18n validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        f"i18n catalogs: {len(template)} messages extracted and at parity across "
        f"{', '.join(shipped)}; compiled catalogs match their sources"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
