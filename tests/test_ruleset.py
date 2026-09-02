"""Guards on the committed branch ruleset — especially that applying it cannot lock the owner out.

`.github/rulesets/main.json` is the in-tree copy of the repository-owned `Protect main`
ruleset, kept committed so the branch-protection posture is reviewable in a pull request
(`docs/standards/CI-CD-STANDARD.md` §5). Until this module was written it carried no
`bypass_actors` key at all, and GitHub reads an absent key exactly as it reads `[]`: nobody
may bypass. Posting the file as committed, with

    gh api -X POST /repos/ChelseaKR/ceqa-preflight/rulesets --input .github/rulesets/main.json

returns `201 Created`, so nothing warns anyone, and the resulting ruleset is one the
repository owner cannot merge past, cannot push past, and cannot force-push or delete her way
out of. The empty list is not a stricter gate. A stricter gate still has a maintainer behind
it; an empty bypass list removes the maintainer, which means the only remaining exit is the
web settings UI, and every automated recovery path is gone with it. That is not hypothetical:
applying a no-bypass ruleset locked the owner out across this portfolio, and restoring access
took a sweep of eighteen repositories.

The live ruleset (id 19155459, read back over the API) does carry the owner's standing bypass,
so the server was configured correctly and the committed artifact was the thing that was wrong.
Nothing under `src/` or `tests/` read the file, so nothing in the repository could contradict
it either. Correcting it once is not the fix, because the file can regress the same way it was
written; this module is the fix, because the regression now fails a test instead of landing
quietly.

Every check here is written to fail closed, in the same spirit as `tests/test_codeql_gate.py`.
`_lockout_risk` is a pure function of an already-parsed document, so it is exercised against
the documents it must reject as well as against the committed one, and `_load_ruleset` treats
a missing or unparseable file as a failure rather than returning an empty document that the
assertions below would then read as "nothing wrong". A guard that passes when its subject is
absent is the defect it exists to catch. The load is a parse and not a text search for the same
reason: a truncated file can still contain the literal string `bypass_actors` and mean nothing
by it.
"""

import json
from pathlib import Path
from typing import Any

import pytest

RULESET = Path(__file__).parents[1] / ".github" / "rulesets" / "main.json"

OWNER_BYPASS = {
    "actor_id": 5,
    "actor_type": "RepositoryRole",
    "bypass_mode": "always",
}
"""The repository owner's standing bypass, and the only entry this file may carry.

`RepositoryRole` 5 is the repository admin role, and this is the entry the live ruleset
carries. `bypass_mode: always` rather than the `pull_request` that CICD-15 in
`docs/standards/CI-CD-STANDARD.md` §5 suggests: a bypass that only works from inside a pull
request is no use when the pull request is the thing that is wedged, which is exactly the
break-glass case. A conflicting pull request never even dispatches the workflow that produces
the required check (see `docs/PR-TRIAGE.md`), so a PR-only bypass can be unreachable at the
moment it is needed. `always` keeps the audited PR path available and keeps a way out when it
is not.
"""


def _load_ruleset() -> dict[str, Any]:
    """The committed ruleset, or a failure. Never a silently empty document.

    The two ways a check like this passes vacuously are a missing file and an unparseable
    one, so both are failures here rather than defaults.
    """
    if not RULESET.is_file():
        pytest.fail(f"{RULESET} is missing, and the committed ruleset is what this module checks")
    try:
        loaded = json.loads(RULESET.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        pytest.fail(f"{RULESET} is not parseable JSON, so nothing can vouch for it: {exc}")
    if not isinstance(loaded, dict):
        pytest.fail(f"{RULESET} is not a JSON object, so it is not a ruleset")
    return loaded


def _lockout_risk(ruleset: dict[str, Any]) -> str | None:
    """Why applying this document would lock the owner out, or `None` if it would not.

    A pure function of a parsed document, so the check can be run against the documents it
    has to reject and not only against the one committed here.
    """
    if "bypass_actors" not in ruleset:
        return "there is no bypass_actors key at all, which GitHub reads as an empty list"
    actors = ruleset["bypass_actors"]
    if not isinstance(actors, list):
        return f"bypass_actors is {type(actors).__name__}, not a list"
    if not actors:
        return (
            "bypass_actors is empty, so applying this leaves no break-glass path and the "
            "owner cannot merge, cannot push, and cannot delete the ruleset blocking her"
        )
    if OWNER_BYPASS not in actors:
        return (
            f"bypass_actors does not carry the owner's standing bypass {OWNER_BYPASS}; "
            f"it carries {actors}"
        )
    return None


def test_applying_the_committed_ruleset_would_not_lock_the_owner_out() -> None:
    """The whole point of this module. This is the assertion an absent or empty list must fail."""
    risk = _lockout_risk(_load_ruleset())
    assert risk is None, (
        f"applying {RULESET.name} as committed would lock the repository owner out: {risk}"
    )


def test_the_owner_is_the_only_bypass_actor() -> None:
    """One actor. A second entry is a real widening of who may skip every rule; this one is not."""
    actors = _load_ruleset()["bypass_actors"]
    assert actors == [OWNER_BYPASS], (
        "the owner's standing bypass is the only entry this file may carry, and a second one "
        f"widens who can skip every rule on the default branch: {actors}"
    )


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({"bypass_actors": []}, "empty"),
        ({}, "no bypass_actors key"),
        ({"bypass_actors": {}}, "not a list"),
        (
            {
                "bypass_actors": [
                    {"actor_id": 1, "actor_type": "Integration", "bypass_mode": "always"}
                ]
            },
            "does not carry the owner",
        ),
        (
            {"bypass_actors": [dict(OWNER_BYPASS, bypass_mode="pull_request")]},
            "does not carry the owner",
        ),
    ],
    ids=["empty", "absent", "wrong-type", "wrong-actor", "wrong-mode"],
)
def test_the_lockout_check_rejects_the_documents_it_must_reject(
    document: dict[str, Any], expected: str
) -> None:
    """Five ways to lose the bypass, every one of which GitHub accepts with a 201 like any other.

    The absent key is the shape that was committed here. The rest are the shapes an edit meant
    to fix it could plausibly land in, including CICD-15's `pull_request` mode.
    """
    risk = _lockout_risk(document)
    assert risk is not None, f"{document} should have been refused"
    assert expected in risk


def test_the_lockout_check_accepts_the_shape_it_should() -> None:
    """A positive control, so the check above cannot be passing by refusing everything."""
    assert _lockout_risk({"bypass_actors": [OWNER_BYPASS]}) is None
