#!/usr/bin/env python3
"""Carry newly wrapped messages into the shipped catalogs without touching anything else.

`make i18n-update` used to tell the author to finish the job by hand with

    pybabel update -i .../messages.pot -d .../locales --omit-header

and that command cannot be run safely against this repository. Measured on Babel 2.18.0,
2026-09-01, against the committed catalogs:

* with `--omit-header`, `pybabel update` deletes the header entry outright. The `es`
  catalog's header is where it states that it is a maintainer draft awaiting the reviewer
  in issue #49, and it is also where `POT-Creation-Date` is pinned -- which
  `docs/I18N.md` pins deliberately, because `scripts/check_i18n.py` recompiles each
  catalog and compares it to the committed `.mo` byte for byte, and Babel invents that
  field from the wall clock whenever a catalog omits it.
* without `--omit-header`, the header entry survives but `POT-Creation-Date` is rewritten
  from the wall clock anyway, and every comment and message in the file is rewrapped, so
  a one-message change arrives as a whole-file diff.

Either way the authoring loop corrupts the pin that the byte comparison depends on. This
script does the same job through the same parser, and writes only what changed:

* messages the template no longer holds are removed;
* messages the template has gained are appended -- with the English `msgstr` equal to its
  `msgid`, which is the identity `check_i18n.py` already enforces, and with an empty
  `msgstr` in every other locale, so `make i18n` stays red until a person translates it;
* every other entry, and the whole header, is left byte for byte alone.

Run it through `make i18n-update`, which extracts the template first and compiles after.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "src" / "ceqa_preflight" / "locales"
TEMPLATE = LOCALES / "messages.pot"

#: `msgstr` for a new message in this locale. English is the identity, because
#: `check_i18n.py` fails when an English translation drifts from its `msgid`; every other
#: locale starts empty so the gate reports it as untranslated rather than shipping the
#: English text as though someone had chosen it.
SOURCE_LOCALE = "en"

#: Babel's own default wrap width, so an entry written here matches one written by
#: `pybabel extract` and a later re-extraction produces no diff.
WIDTH = 76


def unquote(lines: list[str]) -> str:
    """Join the PO string literals on ``lines`` into the string they encode."""

    parts = []
    for line in lines:
        body = line.strip()
        if body.startswith(("msgid ", "msgstr ")):
            body = body.split(" ", 1)[1].strip()
        if not (body.startswith('"') and body.endswith('"')):
            raise ValueError(f"not a PO string literal: {line!r}")
        parts.append(body[1:-1].replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\"))
    return "".join(parts)


def quote(keyword: str, value: str) -> list[str]:
    """Render ``value`` as a `msgid`/`msgstr`, wrapped the way Babel wraps."""

    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    if len(escaped) + len(keyword) + 3 <= WIDTH:
        return [f'{keyword} "{escaped}"']
    chunks = textwrap.wrap(escaped, width=WIDTH - 2, break_long_words=False, break_on_hyphens=False)
    lines = [f'{keyword} ""']
    for index, chunk in enumerate(chunks):
        lines.append(f'"{chunk}{"" if index == len(chunks) - 1 else " "}"')
    return lines


def parse(path: Path) -> tuple[list[str], dict[str, int]]:
    """Split a catalog into blank-line-separated entries, indexed by `msgid`."""

    blocks = path.read_text(encoding="utf-8").split("\n\n")
    index: dict[str, int] = {}
    for position, block in enumerate(blocks):
        lines = [line for line in block.split("\n") if line.strip()]
        if not any(line.startswith("msgid ") for line in lines):
            continue
        start = next(i for i, line in enumerate(lines) if line.startswith("msgid "))
        stop = next(i for i, line in enumerate(lines) if line.startswith("msgstr "))
        index[unquote(lines[start:stop])] = position
    return blocks, index


def update(catalog: Path, wanted: list[str], locale: str) -> tuple[list[str], list[str]]:
    """Add and remove entries so ``catalog`` holds exactly ``wanted``. Returns the delta."""

    blocks, index = parse(catalog)
    present = {message for message in index if message}
    added = [message for message in wanted if message not in present]
    removed = sorted(present - set(wanted))

    kept: list[str | None] = list(blocks)
    for message in removed:
        kept[index[message]] = None
    entries = [block for block in kept if block is not None and block.strip()]
    for message in added:
        entry = ["#, python-brace-format"] if "{" in message else []
        entry += quote("msgid", message)
        entry += quote("msgstr", message if locale == SOURCE_LOCALE else "")
        entries.append("\n".join(entry))
    catalog.write_text("\n\n".join(block.strip("\n") for block in entries) + "\n", encoding="utf-8")
    return added, removed


def main(locales: Path = LOCALES) -> int:
    template = locales / "messages.pot"
    if not template.exists():
        print(f"no extraction template at {template}; run `make i18n-update`", file=sys.stderr)
        return 1
    _, index = parse(template)
    wanted = [message for message in index if message]
    if not wanted:
        print(f"{template} holds no message; refusing to empty every catalog", file=sys.stderr)
        return 1

    untranslated = 0
    for directory in sorted(path for path in locales.iterdir() if path.is_dir()):
        catalog = directory / "LC_MESSAGES" / "messages.po"
        if not catalog.exists():
            continue
        added, removed = update(catalog, wanted, directory.name)
        if directory.name != SOURCE_LOCALE:
            untranslated += len(added)
        print(f"{directory.name}: +{len(added)} -{len(removed)}")
    if untranslated:
        print(
            f"{untranslated} message(s) need a translation before `make i18n` will pass",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
