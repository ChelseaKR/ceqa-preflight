"""Guards on the workflow pins that Dependabot has to be able to read.

`release.yml` pins a reusable workflow held in ChelseaKR/portfolio-standards, a
*private* repository. Dependabot's repo-scoped credentials cannot read it, and a
single unreachable dependency fails the whole weekly update run. The mitigation
is an explicit `ignore` entry in `.github/dependabot.yml`; this module keeps that
entry and the `uses:` line it refers to from drifting apart.
"""

import re
from pathlib import Path

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
