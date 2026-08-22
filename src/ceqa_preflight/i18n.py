"""Deterministic gettext seam for user-facing prose (docs/I18N.md).

Locale selection happens once, explicitly, at the CLI boundary (``ceqa_preflight.cli``):
the ``--locale`` option, then the ``CEQA_PREFLIGHT_LOCALE`` environment variable, then a
deterministic ``en`` fallback. This module never reads the OS locale, the client IP, or
filing-package content to choose a language — that would make report language a hidden,
non-reproducible input. An unsupported-but-valid BCP 47 tag falls back to English rather
than erroring, so a typo in a deployment's environment cannot take the tool down; a
malformed tag is rejected because it cannot correctly resolve to any locale.

Every localizable string is a plain English literal used as its own msgid: modules call
``_(SOME_CONSTANT).format(...)`` at render time, never at import time, so the active locale
at the moment of rendering — not at process start — determines the language. Command
names, JSON field names, rule IDs, finding status values, and source citations are never
passed through ``_()``; they are stable, machine-readable identifiers (docs/I18N.md).
"""

from __future__ import annotations

import gettext
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DOMAIN = "ceqa_preflight"
LOCALE_DIR = Path(__file__).parent / "locales"

# The locales this build ships reviewed-or-drafted catalogs for. Keep in sync with the
# committed `locales/<code>/LC_MESSAGES/ceqa_preflight.po` directories.
SUPPORTED_LOCALES: tuple[str, ...] = ("en", "es")
DEFAULT_LOCALE = "en"

# RFC 5646 (BCP 47) language tags, in the simplified form this tool accepts: a primary
# subtag plus optional hyphen-separated subtags. Full BCP 47 grammar is far richer than
# this tool needs — it only ever resolves the primary subtag against SUPPORTED_LOCALES.
_BCP47 = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


class InvalidLocaleTagError(ValueError):
    """Raised when a requested locale is not a syntactically valid BCP 47 tag."""


def is_valid_bcp47(tag: str) -> bool:
    """Return whether ``tag`` is a syntactically valid (simplified) BCP 47 language tag."""

    return bool(_BCP47.match(tag))


def resolve_locale(requested: str | None) -> str:
    """Resolve a requested locale tag to one of SUPPORTED_LOCALES.

    ``requested`` is typically the raw ``--locale`` option or ``CEQA_PREFLIGHT_LOCALE``
    value. ``None`` (nothing requested) resolves to DEFAULT_LOCALE. A syntactically invalid
    tag raises InvalidLocaleTagError so a typo is reported, not silently swallowed. A
    syntactically valid tag for a locale this build does not ship (e.g. "fr") resolves to
    DEFAULT_LOCALE — deterministic fallback, not an error, per docs/I18N.md.
    """

    if requested is None:
        return DEFAULT_LOCALE
    if not is_valid_bcp47(requested):
        raise InvalidLocaleTagError(f"{requested!r} is not a valid BCP 47 language tag")
    primary = requested.split("-")[0].lower()
    return primary if primary in SUPPORTED_LOCALES else DEFAULT_LOCALE


_translations: dict[str, gettext.NullTranslations] = {}
_active_locale = DEFAULT_LOCALE


def _translation(locale: str) -> gettext.NullTranslations:
    cached = _translations.get(locale)
    if cached is None:
        # fallback=True: a locale with no compiled catalog (or a missing key within one)
        # degrades to the English msgid rather than raising, matching the deterministic
        # English fallback this module promises everywhere else.
        cached = gettext.translation(
            DOMAIN, localedir=LOCALE_DIR, languages=[locale], fallback=True
        )
        _translations[locale] = cached
    return cached


def set_locale(locale: str) -> None:
    """Set the process-wide active locale. Call once, at the CLI boundary, per invocation."""

    global _active_locale
    _active_locale = locale


def get_locale() -> str:
    """Return the currently active locale."""

    return _active_locale


@contextmanager
def using_locale(locale: str) -> Iterator[None]:
    """Temporarily set the active locale (tests; anywhere state must not leak)."""

    previous = _active_locale
    set_locale(locale)
    try:
        yield
    finally:
        set_locale(previous)


def gettext_(message: str) -> str:
    """Translate ``message`` under the currently active locale."""

    return _translation(_active_locale).gettext(message)


def ngettext_(singular: str, plural: str, n: int) -> str:
    """Translate a plural form under the currently active locale."""

    return _translation(_active_locale).ngettext(singular, plural, n)


# Conventional gettext alias. Import as ``from ceqa_preflight.i18n import _``.
_ = gettext_
