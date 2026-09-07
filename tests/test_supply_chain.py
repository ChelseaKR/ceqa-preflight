"""Guards on the reusable-workflow pins that decide whether a release can run at all.

`release.yml` calls a reusable authorize workflow from another repository, and for
months it named ChelseaKR/portfolio-standards, which is *private*. A **public**
repository cannot call a reusable workflow that lives in a private one, and GitHub
reports that as a missing file rather than as a permission error, so it read as a
typo for months rather than as a broken release path.

Measured 2026-09-07 by dispatching `release.yml` on `main`::

    HTTP 422: Invalid Argument - failed to parse workflow: error parsing called workflow
    "ChelseaKR/portfolio-standards/.github/workflows/release-authorize.yml@3692aa52..."
    : workflow was not found

The commit existed, the file existed at it, and the standards repository's Actions
access level was already `user`. The workflow simply could not be dispatched -- not one
job, not one step. Re-pinning to the public mirror at ChelseaKR/.github and changing
nothing else made the same dispatch succeed.
"""

import re
from pathlib import Path

import yaml

_THIS_REPO = "chelseakr/ceqa-preflight"
_PINNED_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*([^@\s]+)@[0-9a-f]{40}")
_IGNORED_NAME = re.compile(r"^\s*-\s*dependency-name:\s*[\"']?([^\"'\s]+)[\"']?\s*$")


def _cross_repo_reusable_workflows(root: Path) -> set[str]:
    """Dependency names Dependabot derives from reusable workflows in other repositories."""
    names: set[str] = set()
    for workflow in sorted((root / ".github/workflows").glob("*.yml")):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            match = _PINNED_USES.match(line)
            if match is None:
                continue
            target = match.group(1).lower()
            # A plain action is `owner/repo`; a reusable workflow carries a path to the
            # workflow file, which is the name Dependabot reports it under.
            if not target.endswith((".yml", ".yaml")):
                continue
            if target.startswith(f"{_THIS_REPO}/"):
                continue
            names.add(target)
    return names


def _dependabot_ignored_dependencies(root: Path) -> set[str]:
    text = (root / ".github/dependabot.yml").read_text(encoding="utf-8")
    return {
        match.group(1).lower()
        for line in text.splitlines()
        if (match := _IGNORED_NAME.match(line)) is not None
    }


#: Repositories under this account that are private, and so cannot host a reusable
#: workflow this public repository calls. Named rather than derived: the check has to work
#: offline, in a suite that runs with sockets disabled, and the failure it exists to catch
#: is a *specific* one this repository shipped for months.
_PRIVATE_REPOSITORIES = ("chelseakr/portfolio-standards",)


def test_no_reusable_workflow_is_called_from_a_private_repository() -> None:
    """The pin that made `release.yml` undispatchable, kept from coming back.

    See this module's docstring for the measurement. The point worth restating is how it
    presented: `workflow was not found`, naming a commit that exists and a file that
    exists at it. Nothing about that message says "this repository is private", which is
    why the pin survived a review, a Dependabot mitigation, and a supply-chain test that
    took the pin's target for granted.
    """
    root = Path(__file__).parents[1]
    referenced = _cross_repo_reusable_workflows(root)

    assert referenced, "expected at least one cross-repository reusable workflow pin"
    unreachable = sorted(
        name
        for name in referenced
        if name.startswith(tuple(f"{repository}/" for repository in _PRIVATE_REPOSITORIES))
    )
    assert not unreachable, (
        "these reusable workflows are called from a private repository, so this public "
        "repository cannot dispatch the workflow that calls them at all -- GitHub reports "
        f"it as `workflow was not found`: {unreachable}"
    )


def test_no_dependabot_ignore_entry_suppresses_a_pin_that_no_longer_exists() -> None:
    """Half of an older guard, kept; the other half is gone and this says why.

    That guard also required *every* cross-repository reusable-workflow pin to carry a
    Dependabot `ignore` entry, because the only such pin lived in a private repository
    Dependabot could not read, and one unreachable dependency failed the whole weekly run.
    The pin is public now, so the requirement is gone and the entry with it: automatic
    updates are restored, and suppressing a readable dependency would hide updates that
    can in fact be made.

    What survives is the stale-entry direction. **It is vacuous today** -- there are no
    ignore entries for it to check -- and it is kept rather than deleted because the
    hazard is a future one: an entry that names nothing suppresses nothing while looking
    like protection, which is exactly the shape the entry it replaced had taken on.
    """
    root = Path(__file__).parents[1]
    referenced = _cross_repo_reusable_workflows(root)
    ignored = _dependabot_ignored_dependencies(root)

    assert ignored <= referenced, (
        "these Dependabot ignore entries no longer match any pinned reusable workflow "
        f"and are suppressing nothing: {sorted(ignored - referenced)}"
    )


def _dependabot_ecosystems(root: Path) -> set[str]:
    document = yaml.safe_load((root / ".github/dependabot.yml").read_text(encoding="utf-8"))
    return {str(entry.get("package-ecosystem")) for entry in document.get("updates", [])}


def test_python_updates_use_the_ecosystem_that_maintains_the_lockfile() -> None:
    """A committed `uv.lock` plus `--locked` installs means Dependabot must speak uv.

    `package-ecosystem: pip` edits `pyproject.toml` and does not know `uv.lock` exists.
    Against workflows that install with `uv sync --locked`, that combination opens pull
    requests that cannot pass: the lockfile is genuinely stale, `--locked` correctly
    refuses it, and CI plus Security go red on every platform before a single test runs.
    PR #59 is the worked example. Dependabot's `uv` ecosystem updates the manifest and
    the lockfile together, so this asserts the pairing rather than trusting a comment.
    """
    root = Path(__file__).parents[1]
    ecosystems = _dependabot_ecosystems(root)

    assert (root / "uv.lock").is_file(), "this guard assumes a committed uv lockfile"
    assert "uv" in ecosystems, (
        "dependabot.yml has no `package-ecosystem: uv` entry, so nothing keeps uv.lock "
        "current and every Python dependency pull request will fail `uv sync --locked`"
    )
    assert "pip" not in ecosystems, (
        "dependabot.yml still declares `package-ecosystem: pip`. With a committed uv.lock "
        "that ecosystem bumps pyproject.toml without relocking, which is exactly what made "
        "PR #59 fail CI and Security on all three platforms"
    )


def test_every_workflow_install_asserts_the_lockfile_is_current() -> None:
    """`--frozen` would make a drifted lockfile install green. Only `--locked` may be used.

    All three workflows carry a comment saying `--locked`, not `--frozen`, and until now a
    comment was the whole of the enforcement. `--frozen` installs the lockfile as-is and
    exits 0 even when pyproject.toml has moved on, so swapping it in is the single easiest
    way to turn a real dependency-drift failure into a permanently green check that has
    stopped verifying anything. It is also the most tempting way to "fix" a red Dependabot
    pull request, which is why this is a test and not prose.
    """
    root = Path(__file__).parents[1]
    installs: list[tuple[str, str]] = []
    for workflow in sorted((root / ".github/workflows").glob("*.yml")):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "uv sync" not in stripped:
                continue
            installs.append((workflow.name, stripped))

    assert installs, "expected at least one `uv sync` install step to guard"
    for name, command in installs:
        assert "--frozen" not in command, (
            f"{name} installs with --frozen: a drifted lockfile would install and pass "
            f"silently. Use --locked, which fails instead. Offending step: {command}"
        )
        assert "--locked" in command, (
            f"{name} runs `uv sync` without --locked, so a lockfile that no longer matches "
            f"pyproject.toml would install and the job would go green. Offending step: {command}"
        )
