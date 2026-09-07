"""Resolve which package a set of staged files belongs to, or refuse to guess.

`pre-commit` hands a hook the paths it staged, not the package they belong to. The hook
has to turn one into the other, and the tempting shortcut -- fall back to the working
directory, or to the files' common parent, when nothing better is found -- is how a hook
becomes a check that cannot fail. Checking the wrong directory produces a report about a
package nobody is filing, and an empty one exits 2 whatever the staged files contained.

So resolution is deliberately narrow. The package is the nearest directory at or above
the staged files' common ancestor that holds a manifest, searched no higher than the
directory the hook was invoked from. A manifest is the only marker used, because it is
the only file whose presence *means* "this directory is a filing package" -- and it names
the filing type, so the hook does not have to be told separately what it is looking at.

When no such directory exists the hook stops and says so, and the operator passes
``--package`` in the hook's ``args``. A refusal a person can fix is worth more than a
pass nobody can trust.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path

#: Filenames `init` writes and `check --manifest` reads. Order is the search order within
#: one directory; a package holding two of them is refused rather than silently ranked.
MANIFEST_NAMES = ("package.yaml", "package.yml", "package.json")


class PackageNotResolved(ValueError):
    """Raised when a staged file set does not identify exactly one filing package."""


def _common_directory(paths: Sequence[Path]) -> Path:
    resolved = [path.resolve() for path in paths]
    directories = [path if path.is_dir() else path.parent for path in resolved]
    common = Path(os.path.commonpath([str(directory) for directory in directories]))
    return common


def manifest_in(directory: Path) -> Path | None:
    """The one manifest in ``directory``, or None. Two manifests are an error, not a tie."""

    found = [directory / name for name in MANIFEST_NAMES if (directory / name).is_file()]
    if len(found) > 1:
        names = ", ".join(path.name for path in found)
        raise PackageNotResolved(f"{directory} holds more than one manifest ({names})")
    return found[0] if found else None


def resolve_package(paths: Iterable[Path], *, boundary: Path) -> tuple[Path, Path]:
    """Return the package directory and its manifest for the staged ``paths``.

    ``boundary`` is the highest directory the search may reach, inclusive. Raises
    :class:`PackageNotResolved` rather than falling back to any directory that has not
    identified itself as a package.
    """

    staged = [path for path in paths]
    if not staged:
        raise PackageNotResolved("no files were passed, so no package could be identified")
    missing = [path for path in staged if not path.exists()]
    if missing:
        listed = ", ".join(str(path) for path in sorted(missing))
        raise PackageNotResolved(f"staged path does not exist: {listed}")

    limit = boundary.resolve()
    candidate = _common_directory(staged)
    if limit != candidate and limit not in candidate.parents:
        raise PackageNotResolved(
            f"staged files lie outside {boundary}; pass --package to name the package"
        )

    while True:
        manifest = manifest_in(candidate)
        if manifest is not None:
            return candidate, manifest
        if candidate == limit:
            break
        candidate = candidate.parent

    names = " or ".join(MANIFEST_NAMES)
    raise PackageNotResolved(
        f"no {names} found at or above {_common_directory(staged)} (searched up to "
        f"{boundary}); pass --package to name the package directory"
    )
