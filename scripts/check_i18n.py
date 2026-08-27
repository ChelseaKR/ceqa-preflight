"""Validate the shipped gettext catalogs before they can reach a report.

`docs/I18N.md` promises four things of `make verify`: that catalogs compile, that EN and
ES are at key and placeholder parity, that every shipped locale tag is valid BCP 47, and
that extraction is fresh. The Makefile's `i18n` target owns compilation and extraction
freshness, because both are naturally expressed as "regenerate and compare". This script
owns the rest, plus two invariants the standard implies but does not name:

* English is a catalog, not an implicit fallback, so every English msgstr must be
  byte-identical to its msgid. Without this, English report prose could drift away from
  the source strings the test suite pins, silently and invisibly.
* A compiled catalog must agree with the `.po` it came from. A stale `.mo` is the exact
  shape of the worst i18n bug: `--locale es` is accepted, no error is raised, and the
  reader gets English while believing they asked for Spanish.
"""

from __future__ import annotations

import gettext
import re
import sys
from collections import Counter
from pathlib import Path

from babel import Locale, UnknownLocaleError
from babel.messages import pofile

ROOT = Path(__file__).resolve().parents[1]
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


def _compiled_failures(catalogs: dict[str, dict[str, str]]) -> list[str]:
    """Prove the compiled catalog a run actually loads says what the `.po` says."""

    failures: list[str] = []
    for locale, messages in catalogs.items():
        compiled = LOCALES / locale / "LC_MESSAGES" / f"{DOMAIN}.mo"
        if not compiled.is_file():
            failures.append(f"{locale}: no compiled catalog; run `make i18n`")
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
            failures.append(f"{locale}: {len(stale)} stale compiled message(s); run `make i18n`")
    return failures


def main() -> int:
    """Fail if any catalog would mislead a reader about the language it is in."""

    failures: list[str] = []
    shipped = _locale_directories()
    failures.extend(_shipped_locale_failures(shipped))

    template = set(_read(TEMPLATE))
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
    failures.extend(_compiled_failures(catalogs))

    if failures:
        print("i18n validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        f"i18n catalogs: {len(template)} messages at parity across "
        f"{', '.join(shipped)}; compiled catalogs match their sources"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
