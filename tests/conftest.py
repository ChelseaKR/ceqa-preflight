"""A census of which rules this suite actually exercises, and in which statuses.

The suite is thorough about *what a rule says* and had nothing measuring *which rules
it ever ran*. Those are different questions, and the second one is the one that decays
silently: a rule added to a pack, or a rule whose only test is deleted in a refactor,
leaves a green suite that has never executed it. This portfolio has measured that shape
repeatedly -- an accessibility gate judging 0 of 17 pages, a code gate judging 0 of 38
codes, a rule-fires gate reaching 28 of 48 -- and in every case the number was available
and simply never printed.

Measured here on 2026-09-10, before this file existed: **26 of 26** catalog rules are
exercised, and every one reaches every status its check can produce. So this gate refuses
nothing today. That is the result, not a reason to skip it -- a coverage figure nobody
prints is a coverage figure that falls without anyone noticing, and the run before the
first regression looks exactly like this one.

Three refusals, all structural. None of them is a number a person maintains:

1. a rule in the catalog that this run never executed;
2. a rule whose check can do more than defer to a person, observed only passing or
   deferring -- `rules/filing.py` already records why that matters in terms: *"A check
   with no reachable failure adds a green line to the report and nothing else."*;
3. a rule whose check does nothing but defer to a person, observed doing something else.

**Manual-only is derived from the code, not from the rule id.** The `-M` in `NOE-M001`
is a naming convention, and a convention is not a declaration. A check counts as
manual-only when every `return` in its own body is a call to `manual_confirmation`, so
the day one of those grows a real failure branch it stops being exempt from refusal 2
without anyone editing a list here.

**The census only runs over a whole, unfiltered, non-collect-only run**, because a
filtered run legitimately executes a handful of rules and a census over it would either
cry wolf or -- worse -- be silenced into meaninglessness to stop it. `--collect-only`
matters specifically: `tests/test_committed_artifacts_are_current.py` shells out with
`--collect-only -q -p no:cacheprovider` to count the suite, and a census that failed that
subprocess would break the test that runs it. Note also that `-p no:cacheprovider`
**deletes `--lf` from the parser**, so every option here is read with `getattr`.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import pytest

_OBSERVED: dict[str, set[str]] = {}

#: The statuses that mean "this rule reached a conclusion of its own" rather than
#: "nothing was wrong" or "a person must look".
_DECIDED = frozenset({"failure", "warning"})


def pytest_configure(config: pytest.Config) -> None:
    """Record every finding the engine returns, without changing what it returns."""

    from ceqa_preflight.rule_engine import RuleEngine

    original = RuleEngine.run

    def run(self, context, *, include_experimental=False):  # type: ignore[no-untyped-def]
        result = original(self, context, include_experimental=include_experimental)
        for finding in result.findings:
            _OBSERVED.setdefault(finding.rule_id, set()).add(finding.status.value)
        return result

    RuleEngine.run = run  # type: ignore[method-assign]


def _returns_only_manual_confirmation(function: Callable[..., object]) -> bool:
    """Whether every ``return`` in this check's own body defers to a person.

    Delegation is deliberately not followed. `noe_primary_form` returns
    `check_primary_form(...)`, which has a reachable failure, so it is not manual-only --
    and reading only the function's own returns gets that right without a call graph.
    """

    try:
        source = inspect.getsource(function)
    except (OSError, TypeError):  # pragma: no cover - a C or generated callable
        return False
    tree = ast.parse(textwrap.dedent(source))
    returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return)]
    if not returns:
        return False
    return all(
        isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "manual_confirmation"
        for node in returns
    )


def _catalog_rules() -> dict[str, str]:
    """Every rule id in the shipped catalog, mapped to its check name."""

    from ceqa_preflight.rule_registry import default_catalog

    return {rule.id: rule.check for rule in default_catalog().rules}


def _whole_unfiltered_run(config: pytest.Config) -> str | None:
    """``None`` when the census may run, else the reason it may not.

    Every option is read with ``getattr``: the option set is whatever plugins are loaded,
    and ``-p no:cacheprovider`` removes ``--lf`` and ``--ff`` from the parser entirely.
    """

    if getattr(config.option, "collectonly", False):
        return "--collect-only: nothing ran"
    if getattr(config.option, "keyword", ""):
        return "-k was given"
    if getattr(config.option, "markexpr", ""):
        return "-m was given"
    if getattr(config.option, "lf", False) or getattr(config.option, "failedfirst", False):
        return "--lf/--ff was given"
    if getattr(config.option, "deselect", None):
        return "--deselect was given"
    testpaths = list(config.getini("testpaths"))
    if testpaths and list(config.args) != testpaths:
        return f"a subset was selected ({' '.join(config.args)})"
    return None


def _refusals(observed: dict[str, set[str]]) -> Iterator[str]:
    from ceqa_preflight.rule_registry import default_registry

    registry = default_registry()
    manual_only = {
        name: _returns_only_manual_confirmation(check) for name, check in registry.items()
    }
    for rule_id, check in sorted(_catalog_rules().items()):
        statuses = observed.get(rule_id, set())
        if not statuses:
            yield (
                f"{rule_id}: no test in this run executed it. A rule the suite never "
                f"runs is a rule whose behaviour is unmeasured, however green the run is."
            )
            continue
        if manual_only.get(check, False):
            extra = sorted(statuses - {"manual"})
            if extra:
                yield (
                    f"{rule_id}: its check ({check}) only ever defers to a person, but "
                    f"this run observed {extra}. Either the check grew a conclusion and "
                    f"the catalog should say so, or something else is emitting under "
                    f"this rule id."
                )
            continue
        if not statuses & _DECIDED:
            yield (
                f"{rule_id}: observed only {sorted(statuses)}. Its check can do more "
                f"than defer to a person, so a run that never sees it conclude anything "
                f"has not tested the half of it that matters. Add a case that makes it "
                f"fail or warn, or make the check manual-only in terms."
            )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Print the two numbers, and fail the run on a structural gap.

    The verdict cannot be a test: no test can assert what a run emitted while the run is
    still emitting. It therefore rides ``session.exitstatus``, which means the summary
    line ("N passed") is **not** the verdict for this suite -- read the process exit code.
    """

    reason = _whole_unfiltered_run(session.config)
    if reason is not None:
        return
    if session.testsfailed:
        print(
            f"\nrule census: not run — {session.testsfailed} test(s) already failed, so "
            "the statuses observed are not the statuses this suite produces."
        )
        return

    catalog = _catalog_rules()
    examined = sorted(rule_id for rule_id in catalog if _OBSERVED.get(rule_id))
    print(f"\nrule census: {len(examined)} of {len(catalog)} catalog rules exercised")
    refusals = list(_refusals(_OBSERVED))
    for refusal in refusals:
        print(f"  RULE CENSUS: {refusal}")
    if refusals:
        session.exitstatus = 1
