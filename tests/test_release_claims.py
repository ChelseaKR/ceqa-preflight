"""The declared version, held against the tag that would make it true.

``main`` says, in five places, that ``v0.1.0`` was released. It was not.
``git tag --list`` is empty here and on ``origin``; ``GET /repos/ChelseaKR/
ceqa-preflight/tags`` returns zero and ``/releases`` returns zero, measured
2026-09-06. What is on ``main`` today:

* the README's opening summary: "``v0.1.0`` is a first tagged release of
  pre-alpha software";
* two install commands pinned to a tag that does not exist,
  ``uvx --from git+https://github.com/ChelseaKR/ceqa-preflight@v0.1.0`` and the
  ``pipx`` equivalent, both of which fail for anyone who runs them, followed by
  "The release attaches a built wheel and sdist, with a CycloneDX SBOM and
  build provenance, to the GitHub Release";
* "Public API and release status": "``v0.1.0`` is the first tagged release";
* the Release & Versioning conformance row, asserting a signed tag authorized
  against ``.github/allowed_signers``, ``make verify`` re-run at the tagged
  commit, and an SBOM and SLSA provenance attached to a GitHub Release;
* ``CITATION.cff``'s ``date-released: "2026-09-02"``, which citation tooling
  prints as the date the software was released, over a comment describing it as
  "the date of the v0.1.0 tag".

All of it arrived in one commit, #76, "release: prepare v0.1.0, the first
tagged release", written in the past tense for an act that never followed. Two
documents in the same tree already contradicted it: ``docs/ROADMAP.md`` says
"no tagged release yet" and ``docs/RESPONSIBLE-TECH-AUDITS.md`` says "No tagged
release has occurred yet."

The reason nothing caught it is the thing this file changes.
``tests/test_manifest.py::test_citation_claims_no_release_date_until_one_is_released``
existed for exactly this, and its own message says "Add date-released only once
a version is actually tagged and released" -- but what it reads is a heading in
``CHANGELOG.md``. Both files were edited in the same commit, so a check of one
document against another agreed, at the moment both stopped being true. A
release claim can only be checked against the release.

So the referent here is ``git tag --list``, and the rule sorts the declared
version into one of two states.

*No tag exists*, which is this repository today. Legitimate: it is pre-release
work, and the wider measurement on 2026-09-06 found twenty public repositories
in this portfolio declaring a version nothing was tagged for. It passes, but
only while the README says so where a reader arrives, in the ``**Status:**``
line or the ``Release & Versioning`` row, in a sentence that names the version
``pyproject.toml`` declares. Naming it is what stops the disclosure going
stale: a bump to ``0.2.0`` under a README still explaining ``0.1.0`` reads
exactly like a current disclosure to anyone who does not diff the two.

*Tags exist and none names the declared version.* A defect, and a failure,
reporting the declared version and the newest tag, because "the version is
wrong" without both numbers sends the reader back to a shell to work out which
two things disagree.

The second state is unreachable from this repository today, so it is driven
from synthetic input on every run rather than waiting for a bad day, next to a
positive control so the rule cannot pass by never passing, and a sabotage of
the real README that asserts the substitution landed before reading the result.

Two things this file deliberately does not do.

It does not create a tag. Cutting ``v0.1.0`` would make every sentence above
true at a stroke, and it is the maintainer's decision, not one a test gets to
make by passing. The prepared release notes are kept, moved back under
``## Unreleased`` where they describe work rather than a release, and
``test_a_tagged_version_has_a_dated_changelog_section`` requires them to be
dated again the moment the tag exists.

It does not reach the network, so it reports the tags this checkout holds and
has to run somewhere that could hold them. ``_why_tags_are_not_authoritative``
refuses to answer from a shallow clone or one configured ``--no-tags``: "no
tags found" from a checkout that was never given any is the vacuous pass this
whole file exists to prevent. ``actions/checkout`` fetches no tags at its
default depth, so the verify job checks out with ``fetch-depth: 0``.

One consequence worth knowing when the tag is finally cut: cut it on the commit
that declares the version. Merging a version bump ahead of its tag puts ``main``
into the failing state above, accurately, because for that window the
repository really does declare a version nothing was tagged for.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
CITATION = REPO_ROOT / "CITATION.cff"

#: Every file that writes the version down again, with the pattern that reads it
#: back. Each is a literal somebody has to remember to change, so each is
#: compared against ``pyproject.toml`` rather than trusted.
RESTATEMENTS: tuple[tuple[Path, str], ...] = (
    (CITATION, r'^version:\s*"?([^"\s#]+)"?'),
    (
        REPO_ROOT / "src" / "ceqa_preflight" / "__init__.py",
        r'^    __version__ = "([^"]+)"',
    ),
)

#: Phrases that say, in English, that nothing has been released. A statement
#: counts as the disclosure only if it carries one of these *and* names the
#: declared version, so neither half can drift away from the other alone.
UNRELEASED_MARKERS = (
    "no tag",
    "not been tagged",
    "no tagged release",
    "not tagged",
    "not yet cut",
    "no signed tag",
    "unreleased",
    "pre-release",
    "prerelease",
    "no release has been",
    "nothing has been released",
    "never been published",
    "no published artifact",
    "no github release",
    "no package registry release",
    "no release exists",
)

#: A tag that names a version: ``v1.2.3``, ``1.2.3``, ``v1.0.0-rc.1``.
_VERSION_TAG = re.compile(r"^v?(?P<version>[0-9]+(?:\.[0-9]+)*(?:[.\-+][0-9A-Za-z.\-+]+)?)$")

#: A CHANGELOG heading carrying a version and a date, i.e. claiming a release.
_DATED_SECTION = re.compile(
    r"^##\s+\[?(?P<version>[0-9][^\]\s]*)\]?[^\n]*?(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})",
    re.MULTILINE,
)

#: A heading saying the current work is not in a release yet.
_UNRELEASED_SECTION = re.compile(r"^##\s+\[?Unreleased\]?", re.MULTILINE | re.IGNORECASE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _declared_version() -> str:
    """The single source of truth: ``[project] version`` in ``pyproject.toml``."""
    version = tomllib.loads(_read(PYPROJECT))["project"]["version"]
    assert isinstance(version, str) and version, "pyproject.toml declares no version"
    return version


# --- Reading the tags, and refusing to read them from a checkout that cannot ---


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell, no untrusted input
        ["git", "-C", str(REPO_ROOT), *args],  # noqa: S607 -- git is the thing being read
        capture_output=True,
        text=True,
        check=False,
    )


def tag_authority_failure(*, inside_work_tree: bool, shallow: bool, tag_option: str) -> str | None:
    """Why this checkout's tag list cannot be read as the repository's tags.

    Split out from the git calls so every refusing branch is reachable from a
    test rather than only from a broken checkout. They share one shape: a
    checkout that was never given tags reports none, and "none found" read as
    "none exist" is the vacuous pass this file exists to prevent.
    """
    if not inside_work_tree:
        return (
            "this is not a git work tree, so there is no tag list to read. Run the "
            "suite from a clone rather than from an unpacked archive"
        )
    if shallow:
        return (
            "this is a shallow clone. actions/checkout fetches no tags at the default "
            "depth, so an empty tag list here would mean 'never fetched', not 'none "
            "exist'. Check out with fetch-depth: 0"
        )
    if tag_option == "--no-tags":
        return (
            "remote.origin.tagOpt is --no-tags, so this clone never fetches tags and "
            "cannot tell an untagged repository from an unfetched one"
        )
    return None


def _why_tags_are_not_authoritative() -> str | None:
    """``tag_authority_failure`` applied to the checkout the suite is running in."""
    try:
        inside = _git("rev-parse", "--is-inside-work-tree")
    except FileNotFoundError:
        return "git is not on PATH, so no tag can be read"
    return tag_authority_failure(
        inside_work_tree=inside.returncode == 0 and inside.stdout.strip() == "true",
        shallow=_git("rev-parse", "--is-shallow-repository").stdout.strip() == "true",
        tag_option=_git("config", "--get", "remote.origin.tagOpt").stdout.strip(),
    )


def _tags() -> tuple[str, ...]:
    """Every tag this checkout holds, having established that it could hold them."""
    reason = _why_tags_are_not_authoritative()
    assert reason is None, f"the tag list here cannot be trusted: {reason}"
    listed = _git("tag", "--list")
    assert listed.returncode == 0, f"`git tag --list` failed: {listed.stderr.strip()}"
    return tuple(line.strip() for line in listed.stdout.splitlines() if line.strip())


def _tag_version(tag: str) -> str | None:
    """The version a tag names, or ``None`` when it names none."""
    found = _VERSION_TAG.match(tag)
    if found is None:
        return None
    version: str = found.group("version")
    return version


def _tag_order(tag: str) -> tuple[tuple[int, ...], str]:
    """Numeric order, because ``git tag --list`` sorts v0.10.0 before v0.9.0."""
    version = _tag_version(tag) or ""
    return tuple(int(number) for number in re.findall(r"[0-9]+", version)), tag


class ReleaseState(NamedTuple):
    """What the tags of a repository say about one declared version."""

    declared: str
    tags: tuple[str, ...]

    @property
    def matching(self) -> tuple[str, ...]:
        """The tags that name the declared version."""
        return tuple(tag for tag in self.tags if _tag_version(tag) == self.declared)

    @property
    def newest(self) -> str | None:
        """The highest-numbered tag, which is what a reader would call current."""
        return max(self.tags, key=_tag_order) if self.tags else None


# --- Where the README is allowed to make the disclosure ----------------------


def _statements(text: str) -> list[str]:
    """Markdown split into paragraphs and table rows, whitespace collapsed.

    A sentence wrapped across three source lines is one statement to a reader,
    and a table row is one statement however its cells are padded.
    """
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.splitlines()
        if any(line.lstrip().startswith("|") for line in lines):
            blocks.extend(lines)
        else:
            blocks.append(block)
    return [" ".join(block.split()) for block in blocks if block.strip()]


def release_status_statements(text: str) -> list[tuple[str, str]]:
    """The two places a reader looks for release status, as they are written."""
    found: list[tuple[str, str]] = []
    for statement in _statements(text):
        if statement.startswith("**Status:**"):
            found.append(("the README's status line", statement))
        elif re.match(r"^\|\s*Release & Versioning\s*\|", statement):
            found.append(("the README's Release & Versioning row", statement))
    return found


# --- The rule itself, as a function of everything it reads -------------------


def release_claim_failure(declared: str, tags: Sequence[str], readme: str) -> str | None:
    """``None`` when the declared version is honest, else what is wrong with it.

    Pure, so both failing branches are exercised on every run by the negative
    controls below instead of waiting for the repository to enter them.
    """
    state = ReleaseState(declared, tuple(tags))
    if state.matching:
        return None
    if state.tags:
        return (
            f"pyproject.toml declares version {declared!r} and no tag names it. "
            f"This checkout holds {len(state.tags)} tag(s) and the newest is "
            f"{state.newest!r}, so {declared!r} is a version number with no artifact "
            "behind it. Cut the tag for the declared version, or move the declaration "
            "back to the version that was released."
        )
    places = release_status_statements(readme)
    if not places:
        return (
            "nothing is tagged, and the README has neither a `**Status:**` line nor a "
            "`Release & Versioning` row, so there is nowhere a reader is told that "
            f"version {declared!r} was never released."
        )
    for _, statement in places:
        lowered = statement.lower()
        if declared in statement and any(marker in lowered for marker in UNRELEASED_MARKERS):
            return None
    return (
        f"nothing is tagged, and {declared!r} is not disclosed as unreleased where a "
        "reader arrives. "
        + " ".join(f"{label} reads: {statement!r}." for label, statement in places)
        + f" One of them has to name {declared!r} and say it is untagged, so the number "
        "is not read as a shipped version, and naming it is what keeps the sentence "
        "from outliving the version it describes."
    )


def restated_version(pattern: str, text: str) -> str | None:
    """The version a restatement pattern reads out of a file, if it finds one."""
    found = re.search(pattern, text, re.MULTILINE)
    if found is None:
        return None
    version: str = found.group(1)
    return version


# --- The gate ----------------------------------------------------------------


def test_this_checkout_can_be_trusted_to_know_the_repositorys_tags() -> None:
    """Asserted before anything reads a tag, so a blind checkout says so.

    Without it, every check below would pass on a shallow CI checkout by finding
    nothing, the gate reporting green precisely when it can see least.
    """
    reason = _why_tags_are_not_authoritative()
    assert reason is None, f"the tag list here cannot be trusted: {reason}"


def test_the_declared_version_is_tagged_or_the_readme_says_it_is_not() -> None:
    """The whole rule, against this repository as it stands."""
    failure = release_claim_failure(_declared_version(), _tags(), _read(README))
    assert failure is None, failure


# --- Negative controls: the arms this repository is not in today -------------

#: A README that discloses nothing, and one that discloses version 0.1.0.
_SILENT_README = "# demo\n\n**Status:** Beta. Ready to use.\n"
_HONEST_README = "# demo\n\n**Status:** Beta. Version `0.1.0`, no tag has been cut.\n"


def test_the_rule_fails_when_tags_exist_and_none_names_the_declared_version() -> None:
    """The defect arm, unreachable from this repository today because it has no tags."""
    failure = release_claim_failure("0.2.0", ("v0.1.0", "v0.1.1"), _HONEST_README)
    assert failure is not None, "tags naming no declared version passed the rule"
    assert "0.2.0" in failure, failure
    assert "v0.1.1" in failure, failure


def test_the_rule_reports_the_newest_tag_rather_than_the_last_listed() -> None:
    """Lexical order puts v0.10.0 before v0.9.0, and the reader wants the newest."""
    failure = release_claim_failure("1.0.0", ("v0.10.0", "v0.9.0"), _HONEST_README)
    assert failure is not None and "v0.10.0" in failure, failure


def test_the_rule_passes_when_a_tag_names_the_declared_version() -> None:
    """The positive control: a released version needs no disclosure at all.

    Without it, the failing branches above would also be satisfied by a rule
    that simply never passes, which is a broken gate in the other direction.
    """
    assert release_claim_failure("0.1.1", ("v0.1.0", "v0.1.1"), _SILENT_README) is None


def test_the_rule_fails_when_nothing_is_tagged_and_the_readme_does_not_say_so() -> None:
    """Being unreleased is fine. Publishing a version number in silence is not."""
    failure = release_claim_failure("0.1.0", (), _SILENT_README)
    assert failure is not None and "0.1.0" in failure, failure


def test_the_rule_fails_when_the_disclosure_names_a_different_version() -> None:
    """A disclosure that does not name the declared version goes stale unseen."""
    assert release_claim_failure("0.2.0", (), _HONEST_README) is not None


def test_the_rule_fails_when_the_readme_offers_nowhere_to_look() -> None:
    failure = release_claim_failure("0.1.0", (), "# demo\n\nNo status anywhere.\n")
    assert failure is not None and "Status" in failure, failure


def test_the_rule_reads_this_readme_rather_than_passing_regardless() -> None:
    """Sabotage the real disclosure and the real check has to notice.

    The controls above run on synthetic text, which leaves one thing unproven:
    that the passing verdict on this repository comes from this repository's
    README. So the declared version is struck out of the real file and the rule
    re-run against it. The substitution is asserted to have changed something
    first, because a sabotage that quietly does nothing reads exactly like a
    passing test.
    """
    declared = _declared_version()
    readme = _read(README)
    sabotaged = readme.replace(declared, "0.0.0-not-the-declared-version")
    assert sabotaged != readme, (
        f"the README never names the declared version {declared!r}, so whatever "
        "disclosure it makes cannot be about the version that is declared"
    )
    assert release_claim_failure(declared, (), sabotaged) is not None, (
        "the README passed the disclosure check with the declared version removed "
        "from it, so the check is not reading what it claims to read"
    )


def test_the_authority_check_refuses_every_checkout_that_cannot_see_tags() -> None:
    """Each argument driven to its failing value, and the healthy case asserted.

    Without the healthy case the refusal could be unconditional, which would
    make the gate unreachable rather than strict.
    """
    assert tag_authority_failure(inside_work_tree=True, shallow=False, tag_option="") is None
    assert tag_authority_failure(inside_work_tree=False, shallow=False, tag_option="") is not None
    assert tag_authority_failure(inside_work_tree=True, shallow=True, tag_option="") is not None
    assert (
        tag_authority_failure(inside_work_tree=True, shallow=False, tag_option="--no-tags")
        is not None
    )


# --- Everywhere else the version is written down -----------------------------


def test_every_restatement_of_the_version_agrees_with_pyproject() -> None:
    """One version, one source. Every copy of it is compared, not trusted."""
    declared = _declared_version()
    disagreeing: list[str] = []
    for path, pattern in RESTATEMENTS:
        relative = path.relative_to(REPO_ROOT)
        restated = restated_version(pattern, _read(path))
        assert restated is not None, (
            f"{relative} no longer restates a version where {pattern!r} looks for one, "
            "so it would have been compared against nothing"
        )
        if restated != declared:
            disagreeing.append(f"{relative} says {restated}")
    assert not disagreeing, f"pyproject.toml declares {declared}; " + "; ".join(disagreeing)


def test_each_restatement_pattern_follows_the_file_it_reads() -> None:
    """Negative control on the extractors, with the mutation asserted first.

    A pattern that matched some unrelated string would agree with
    ``pyproject.toml`` only by accident, and would go on agreeing after the
    literal it was supposed to be watching changed. Substituting a sentinel and
    requiring the pattern to return the sentinel proves each one is reading the
    literal it is named for.
    """
    declared = _declared_version()
    sentinel = "9.99.999"
    for path, pattern in RESTATEMENTS:
        relative = path.relative_to(REPO_ROOT)
        original = _read(path)
        mutated = original.replace(declared, sentinel)
        assert mutated != original, f"{relative} does not contain {declared!r}"
        assert restated_version(pattern, mutated) == sentinel, (
            f"{pattern!r} did not follow the version literal in {relative}, so the "
            "agreement it reports is about something else"
        )


def test_citation_declares_a_release_date_only_for_a_version_that_was_tagged() -> None:
    """``date-released`` is the field a citation manager prints as the release date.

    Carrying one with nothing tagged publishes a release date for a release that
    does not exist, which is the same defect as the version number and harder to
    spot, because the date is real. It is just the date of something else. Bound
    in both directions, so it cannot be dropped from a real release either.
    """
    dated = [line for line in _read(CITATION).splitlines() if line.startswith("date-released:")]
    tagged = ReleaseState(_declared_version(), _tags()).matching
    assert bool(dated) == bool(tagged), (
        f"CITATION.cff {'declares' if dated else 'omits'} date-released while the "
        f"declared version is {'tagged as ' + str(tagged) if tagged else 'untagged'}"
    )


def test_every_dated_changelog_section_names_a_version_that_was_tagged() -> None:
    """A dated section is the CHANGELOG saying that version shipped."""
    tags = _tags()
    tagged = {_tag_version(tag) for tag in tags}
    claimed: list[str] = [
        found.group("version") for found in _DATED_SECTION.finditer(_read(CHANGELOG))
    ]
    unbacked = [version for version in claimed if version not in tagged]
    assert not unbacked, (
        f"CHANGELOG.md dates a release for {unbacked} and this checkout holds "
        f"{list(tags)}, so those sections describe releases that were never cut"
    )


def test_the_changelog_says_the_current_work_is_unreleased_while_it_is() -> None:
    """The reader who scrolls past the README lands here next."""
    if ReleaseState(_declared_version(), _tags()).matching:
        return
    assert _UNRELEASED_SECTION.search(_read(CHANGELOG)), (
        "nothing is tagged and CHANGELOG.md has no `## [Unreleased]` heading, so its "
        "topmost section reads as the log of a release that happened"
    )


def test_the_changelog_patterns_tell_a_dated_section_from_an_unreleased_one() -> None:
    """Negative control: both patterns shown finding, and shown not finding."""
    dated = "# c\n\n## [1.2.3] - 2026-01-02\n\n- a change\n"
    unreleased = "# c\n\n## [Unreleased]\n\n- a change\n"
    assert [found.group("version") for found in _DATED_SECTION.finditer(dated)] == ["1.2.3"]
    assert not list(_DATED_SECTION.finditer(unreleased))
    assert _UNRELEASED_SECTION.search(unreleased)
    assert not _UNRELEASED_SECTION.search(dated)


def test_a_version_tag_is_recognised_however_it_is_written() -> None:
    """The comparison is on versions, not on how a tag spells one."""
    assert _tag_version("v0.1.0") == "0.1.0"
    assert _tag_version("0.1.0") == "0.1.0"
    assert _tag_version("v1.0.0-rc.1") == "1.0.0-rc.1"
    assert _tag_version("standards-v1") is None
    assert _tag_version("latest") is None


def test_a_tagged_version_has_a_dated_changelog_section() -> None:
    """The other direction, and the one that makes the un-dating reversible.

    ``## [0.1.0] - 2026-09-02`` sat above a release that was never cut, so the
    section was moved back under ``## Unreleased``. This is what asks for it
    back: the moment a tag names the declared version, the CHANGELOG has to
    date a section for it again, or the release ships with no entry.
    """
    state = ReleaseState(_declared_version(), _tags())
    if not state.matching:
        return
    dated = [found.group("version") for found in _DATED_SECTION.finditer(_read(CHANGELOG))]
    assert state.declared in dated, (
        f"{state.matching} names version {state.declared}, and CHANGELOG.md dates "
        f"sections for {dated or 'nothing'}. A released version needs a dated section"
    )
