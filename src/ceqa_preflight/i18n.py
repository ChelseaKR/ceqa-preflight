"""The gettext seam: explicit locale selection with deterministic English fallback.

`docs/I18N.md` draws the boundary this module enforces. Console messages, HTML report
prose, finding summaries, remediation guidance, and user-visible errors are localizable
content and pass through :func:`gettext` here. Command names, machine-readable JSON field
names, rule identifiers, finding status values, and source citations are stable
identifiers and never reach a catalog.

Locale selection is explicit at the command-line boundary. Nothing in this module reads
an environment variable, a network response, or the content of a filing package to guess
a language: a run that was not told which language to use is an English run, every time.
That is what makes a report reproducible from its command line alone.
"""

from __future__ import annotations

import gettext as _gettext
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from importlib import resources

DOMAIN = "messages"
DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES: tuple[str, ...] = ("en", "es")

# RFC 5646 well-formedness, narrowed to the shapes a command-line locale flag realistically
# carries: a 2-3 letter primary language, an optional 4-letter script, and an optional
# region that is either two letters or three digits. Extensions, private use, and variant
# subtags are refused rather than silently ignored, because accepting a tag this tool
# cannot act on would look like support it does not have. `[0-9]` is written out because
# `\d` in Python matches every Unicode decimal digit, which would let a fullwidth region
# subtag through.
_WELL_FORMED_TAG = re.compile(
    r"^[A-Za-z]{2,3}(-[A-Za-z]{4})?(-([A-Za-z]{2}|[0-9]{3}))?$",
)

_active: ContextVar[str] = ContextVar("ceqa_preflight_locale", default=DEFAULT_LOCALE)


class LocaleError(ValueError):
    """Raised when a requested locale tag is not a well-formed language tag."""


def normalize_tag(tag: str) -> str:
    """Return the canonical casing of a well-formed language tag.

    Raises :class:`LocaleError` for anything that is not well formed, so a typo is
    reported to the person who typed it instead of quietly becoming English.
    """

    candidate = tag.strip().replace("_", "-")
    if not _WELL_FORMED_TAG.match(candidate):
        raise LocaleError(f"{tag!r} is not a well-formed language tag")
    parts = candidate.split("-")
    canonical = [parts[0].lower()]
    for part in parts[1:]:
        canonical.append(part.title() if len(part) == 4 else part.upper())
    return "-".join(canonical)


def resolve(tag: str | None) -> tuple[str, str | None]:
    """Map a requested tag onto a shipped catalog.

    Returns the catalog that will be used and the tag that was asked for but not shipped,
    or ``None`` when the request was met exactly. A caller that gets a non-``None`` second
    value has fallen back to English and is expected to say so; silently downgrading the
    language of an advisory report would be a withheld fact.
    """

    if tag is None:
        return DEFAULT_LOCALE, None
    normalized = normalize_tag(tag)
    language = normalized.split("-")[0]
    if language in SUPPORTED_LOCALES:
        return language, None
    return DEFAULT_LOCALE, normalized


def active_locale() -> str:
    """Return the catalog currently in force for this context."""

    return _active.get()


def set_locale(locale: str) -> str:
    """Put one shipped catalog in force, and return the one it replaced.

    The command-line boundary calls this once, after :func:`resolve` has already mapped a
    requested tag onto something that ships. It returns the previous catalog so the caller
    can put it back: a process that runs more than one command, such as a test suite or an
    embedding application, must not inherit the language of whatever ran before it.
    """

    if locale not in SUPPORTED_LOCALES:
        raise LocaleError(f"{locale!r} is not a shipped catalog")
    previous = _active.get()
    _active.set(locale)
    return previous


@contextmanager
def use_locale(locale: str) -> Iterator[str]:
    """Run a block against one shipped catalog, restoring the previous one afterwards."""

    if locale not in SUPPORTED_LOCALES:
        raise LocaleError(f"{locale!r} is not a shipped catalog")
    token = _active.set(locale)
    try:
        yield locale
    finally:
        _active.reset(token)


@lru_cache(maxsize=len(SUPPORTED_LOCALES))
def _translation(locale: str) -> _gettext.GNUTranslations:
    """Load one compiled catalog, refusing to fall back to an untranslated stand-in.

    ``fallback=False`` is the point: a missing or unreadable catalog raises here rather
    than returning a :class:`gettext.NullTranslations` that would render English while the
    report claimed to be in another language.
    """

    catalog_root = resources.files("ceqa_preflight").joinpath("locales")
    with resources.as_file(catalog_root) as localedir:
        translation = _gettext.translation(
            DOMAIN, localedir=str(localedir), languages=[locale], fallback=False
        )
    if not isinstance(translation, _gettext.GNUTranslations):  # pragma: no cover - defensive
        raise TypeError("compiled gettext catalog did not load as GNUTranslations")
    return translation


def gettext(message: str) -> str:
    """Translate one message into the active locale."""

    return _translation(active_locale()).gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    """Translate a countable message, using the active catalog's plural rule."""

    return _translation(active_locale()).ngettext(singular, plural, count)
