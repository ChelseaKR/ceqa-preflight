"""Enforce the i18n release gate's `make verify` obligations (docs/I18N.md).

Checks, for every locale in ``ceqa_preflight.i18n.SUPPORTED_LOCALES``:

1. extraction freshness — the committed POT's msgid set matches what re-extracting the
   current source tree would produce, so a new ``_()`` call can't silently ship untranslated;
2. BCP 47 validity of the locale directory name itself;
3. key parity — the catalog's msgid set matches the committed POT's;
4. placeholder parity — every ``{name}`` / ``%(name)s`` token in a translated msgid also
   appears in its msgstr, so a translation can't drop or typo a substitution and crash at
   render time; and
5. the committed compiled ``.mo`` matches the committed ``.po`` it should have been compiled
   from, so a source edit to the ``.po`` can't ship without ``make i18n-compile``.

Maintainer-only, like ``scripts/check_rule_sources.py``: it needs Babel (a dev dependency),
never the network, and is wired into `make verify` as `make i18n-check`.
"""

from __future__ import annotations

import gettext
import io
import re
import sys
from pathlib import Path

from babel.messages.extract import extract_from_dir
from babel.messages.frontend import parse_mapping_cfg
from babel.messages.mofile import write_mo
from babel.messages.pofile import PoFileError, read_po

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = str(ROOT / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ceqa_preflight.i18n import SUPPORTED_LOCALES, is_valid_bcp47  # noqa: E402

SRC = ROOT / "src"
LOCALE_DIR = SRC / "ceqa_preflight" / "locales"
POT_PATH = LOCALE_DIR / "ceqa_preflight.pot"

# {name} / {name:.1f} / {name!r} — the substitution name only, not the format spec.
_BRACE_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}")
# %(name)s — Jinja's i18n extension always extracts {% trans %} placeholders this way.
_PERCENT_PLACEHOLDER = re.compile(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)[a-zA-Z]")


def _placeholders(text: str) -> set[str]:
    return set(_BRACE_PLACEHOLDER.findall(text)) | set(_PERCENT_PLACEHOLDER.findall(text))


def _extracted_msgids() -> set[str]:
    with (ROOT / "babel.cfg").open(encoding="utf-8") as handle:
        method_map, options_map = parse_mapping_cfg(handle)
    msgids = set()
    for _filename, _lineno, message, _comments, _context in extract_from_dir(
        SRC, method_map, options_map
    ):
        msgids.add(message if isinstance(message, str) else message[0])
    return msgids


def _committed_pot_msgids() -> set[str]:
    with POT_PATH.open("rb") as handle:
        catalog = read_po(handle)
    return {message.id for message in catalog if message.id}


def _pot_freshness_errors(pot_msgids: set[str]) -> list[str]:
    current_msgids = _extracted_msgids()
    if pot_msgids == current_msgids:
        return []
    added = current_msgids - pot_msgids
    removed = pot_msgids - current_msgids
    detail = []
    if added:
        detail.append(f"new in source, missing from POT: {sorted(added)!r}")
    if removed:
        detail.append(f"in POT, no longer in source: {sorted(removed)!r}")
    return ["POT is stale (run `make i18n-extract` and commit the result): " + "; ".join(detail)]


def _key_parity_errors(po_path: Path, catalog_msgids: set[str], pot_msgids: set[str]) -> list[str]:
    if catalog_msgids == pot_msgids:
        return []
    missing = pot_msgids - catalog_msgids
    extra = catalog_msgids - pot_msgids
    detail = []
    if missing:
        detail.append(f"missing keys: {sorted(missing)!r}")
    if extra:
        detail.append(f"stale keys not in POT: {sorted(extra)!r}")
    return [f"{po_path}: key parity failed — " + "; ".join(detail)]


def _placeholder_errors(po_path: Path, catalog: object) -> list[str]:
    errors = []
    for message in catalog:  # type: ignore[attr-defined]
        if not message.id or not message.string:
            continue
        msgid = message.id if isinstance(message.id, str) else message.id[0]
        msgstr = message.string if isinstance(message.string, str) else message.string[0]
        source_placeholders = _placeholders(msgid)
        target_placeholders = _placeholders(msgstr)
        if source_placeholders != target_placeholders:
            errors.append(
                f"{po_path}: placeholder mismatch in {msgid!r} -> {msgstr!r} "
                f"(source has {sorted(source_placeholders)!r}, "
                f"translation has {sorted(target_placeholders)!r})"
            )
    return errors


def _mo_freshness_errors(
    po_path: Path, mo_path: Path, catalog: object, pot_msgids: set[str]
) -> list[str]:
    if not mo_path.exists():
        return [f"missing {mo_path}; run `make i18n-compile`"]
    buffer = io.BytesIO()
    write_mo(buffer, catalog)
    buffer.seek(0)
    fresh = gettext.GNUTranslations(buffer)
    with mo_path.open("rb") as handle:
        committed = gettext.GNUTranslations(handle)
    # Compare the translation mapping only: write_mo embeds a Babel-version-derived header
    # that legitimately differs run to run, and that is not what "matches its .po" checks.
    fresh_map = {key: fresh.gettext(key) for key in pot_msgids}
    committed_map = {key: committed.gettext(key) for key in pot_msgids}
    if fresh_map == committed_map:
        return []
    return [f"{mo_path} is stale relative to {po_path}; run `make i18n-compile`"]


def _locale_errors(locale: str, pot_msgids: set[str]) -> list[str]:
    errors = []
    if not is_valid_bcp47(locale):
        errors.append(f"{locale!r} in SUPPORTED_LOCALES is not a valid BCP 47 tag")
    catalog_dir = LOCALE_DIR / locale / "LC_MESSAGES"
    po_path = catalog_dir / "ceqa_preflight.po"
    mo_path = catalog_dir / "ceqa_preflight.mo"
    if not po_path.exists():
        errors.append(f"missing {po_path}")
        return errors
    try:
        with po_path.open("rb") as handle:
            catalog = read_po(handle, locale=locale, domain="ceqa_preflight")
    except PoFileError as error:
        errors.append(f"{po_path}: {error}")
        return errors
    catalog_msgids = {message.id for message in catalog if message.id}
    errors.extend(_key_parity_errors(po_path, catalog_msgids, pot_msgids))
    errors.extend(_placeholder_errors(po_path, catalog))
    errors.extend(_mo_freshness_errors(po_path, mo_path, catalog, pot_msgids))
    return errors


def main() -> int:
    if not POT_PATH.exists():
        return _report([f"missing {POT_PATH}; run `make i18n-extract`"])

    pot_msgids = _committed_pot_msgids()
    errors = _pot_freshness_errors(pot_msgids)
    for locale in SUPPORTED_LOCALES:
        errors.extend(_locale_errors(locale, pot_msgids))
    return _report(errors)


def _report(errors: list[str]) -> int:
    if not errors:
        print(f"i18n check passed for locales: {', '.join(SUPPORTED_LOCALES)}")
        return 0
    print("i18n check failed:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
