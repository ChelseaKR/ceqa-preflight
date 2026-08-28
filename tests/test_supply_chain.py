"""Guards on the workflow pins that Dependabot has to be able to read.

`release.yml` pins a reusable workflow held in ChelseaKR/portfolio-standards, a
*private* repository. Dependabot's repo-scoped credentials cannot read it, and a
single unreachable dependency fails the whole weekly update run. The mitigation
is an explicit `ignore` entry in `.github/dependabot.yml`; this module keeps that
entry and the `uses:` line it refers to from drifting apart.
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


def test_dependabot_ignores_every_cross_repo_reusable_workflow_pin() -> None:
    """Keep `.github/dependabot.yml` and the workflow pins from drifting apart.

    Dependabot cannot read a reusable workflow held in a private repository under a
    personal account. One unreachable dependency fails the entire weekly update run
    even when every other action was checked and its pull requests were opened, so
    each such pin has to be ignored explicitly.

    Both directions are asserted, so that neither a renamed workflow nor a stale
    ignore entry can quietly reintroduce the weekly failure or quietly suppress a
    dependency that Dependabot could in fact have updated.
    """
    root = Path(__file__).parents[1]
    referenced = _cross_repo_reusable_workflows(root)
    ignored = _dependabot_ignored_dependencies(root)

    assert referenced, "expected at least one cross-repository reusable workflow pin"
    assert referenced <= ignored, (
        "these cross-repository reusable workflows are pinned but not ignored by "
        f"Dependabot, so the weekly update job will fail on them: {sorted(referenced - ignored)}"
    )
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
