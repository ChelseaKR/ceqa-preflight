"""The rule census's own moving parts, held to tests.

The census in `tests/conftest.py` rides `session.exitstatus`, so no test can assert its
verdict while the run producing that verdict is still going. What *can* be tested is
every piece it is built from -- the classifier that decides which checks are manual-only,
the discriminator that decides whether a run is censusable at all, and the refusal
generator -- and those are the parts that can silently stop working.

The verdict half is proven by a control recorded in the pull request: with
`test_warns_for_large_files_and_marks_unknown_sizes_manual` rewritten so it no longer
makes FILE-004 warn but still passes, the suite reports the same collected count and the
same "N passed", and the process exits 1 naming FILE-004. That shape -- a sabotage that
leaves the test list untouched -- is the only one that isolates a session-level gate,
because any sabotage that changes what is collected is caught by
`test_readme_test_total_matches_what_pytest_collects` first, and a failed test
short-circuits the census by design.
"""

from __future__ import annotations

from typing import Any

import conftest
import pytest

from ceqa_preflight.rule_registry import default_catalog, default_registry


def test_a_check_that_only_defers_to_a_person_is_recognised_as_manual_only() -> None:
    """And one that delegates to a check with a reachable failure is not.

    `noe_primary_form` returns `check_primary_form(...)`, which can fail. Following the
    delegation is unnecessary and would need a call graph; reading only the function's own
    returns gets both cases right.
    """

    registry = default_registry()

    assert conftest._returns_only_manual_confirmation(registry["noe_exemption"]) is True
    assert conftest._returns_only_manual_confirmation(registry["nod_cdfw_fee"]) is True
    assert conftest._returns_only_manual_confirmation(registry["noe_primary_form"]) is False
    assert conftest._returns_only_manual_confirmation(registry["pdf_readable"]) is False


def test_the_manual_only_set_is_neither_empty_nor_everything() -> None:
    """Both floors, because either extreme makes a refusal vacuous.

    An empty set makes refusal 3 unreachable; a full set makes refusal 2 unreachable. The
    classifier returning one of those is what a classifier that stopped parsing returns.
    """

    registry = default_registry()
    manual_only = {
        name
        for name, check in registry.items()
        if conftest._returns_only_manual_confirmation(check)
    }

    assert manual_only, "no check reads as manual-only; refusal 3 could never fire"
    assert manual_only != set(registry), "every check reads as manual-only; refusal 2 is dead"
    # Six by name rather than by count: a count is a number someone maintains.
    assert manual_only == {
        "noe_exemption",
        "noe_supporting_findings",
        "noe_signature_timing",
        "nod_cdfw_fee",
        "nod_supporting_materials",
        "nod_signature_timing",
    }


def test_every_catalog_rule_maps_to_a_registered_check() -> None:
    """The census's denominator, and a floor on it.

    `_catalog_rules()` returning `{}` is what a reader that stopped finding the rulepacks
    returns, and an empty denominator makes "N of N exercised" true for free.
    """

    catalog = conftest._catalog_rules()
    registry = default_registry()

    assert len(catalog) == len(default_catalog().rules)
    assert catalog, "the census denominator is empty; every refusal would be vacuous"
    assert set(catalog.values()) <= set(registry)


class _Option:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


class _Config:
    def __init__(self, args: list[str], testpaths: list[str], **option: Any) -> None:
        self.args = args
        self._testpaths = testpaths
        self.option = _Option(**option)

    def getini(self, name: str) -> Any:
        assert name == "testpaths"
        return self._testpaths


def test_a_whole_unfiltered_run_is_censusable_and_a_filtered_one_is_not() -> None:
    """Both directions. A discriminator that refuses everything disables the gate
    silently, and one that accepts everything makes it cry wolf on `pytest -k`.
    """

    whole = _Config(["tests"], ["tests"], collectonly=False, keyword="", markexpr="")
    assert conftest._whole_unfiltered_run(whole) is None

    for label, config in {
        "collect-only": _Config(["tests"], ["tests"], collectonly=True, keyword="", markexpr=""),
        "-k": _Config(["tests"], ["tests"], collectonly=False, keyword="foo", markexpr=""),
        "-m": _Config(["tests"], ["tests"], collectonly=False, keyword="", markexpr="slow"),
        "--lf": _Config(["tests"], ["tests"], collectonly=False, keyword="", markexpr="", lf=True),
        "--deselect": _Config(
            ["tests"],
            ["tests"],
            collectonly=False,
            keyword="",
            markexpr="",
            deselect=["tests/test_x.py::test_y"],
        ),
        "one file": _Config(
            ["tests/test_common_rules.py"],
            ["tests"],
            collectonly=False,
            keyword="",
            markexpr="",
        ),
    }.items():
        assert conftest._whole_unfiltered_run(config) is not None, label


def test_an_absent_lf_option_does_not_crash_the_discriminator() -> None:
    """`-p no:cacheprovider` deletes `--lf` and `--ff` from the parser entirely.

    `config.option.lf` then raises `AttributeError` from inside a hook, which surfaces as
    a hook crash and exit 1 on whichever subprocess was running --- and this repository
    has exactly such a subprocess: `test_readme_test_total_matches_what_pytest_collects`
    shells out with `--collect-only -q -p no:cacheprovider`.
    """

    without_cache_plugin = _Config(["tests"], ["tests"], collectonly=False, keyword="", markexpr="")
    assert not hasattr(without_cache_plugin.option, "lf")
    assert conftest._whole_unfiltered_run(without_cache_plugin) is None


def _first_rule_with_check(predicate: Any) -> str:
    for rule in default_catalog().rules:
        if predicate(rule.check):
            return rule.id
    raise AssertionError("no rule matched")


def test_the_three_refusals_fire_on_the_observations_that_deserve_them() -> None:
    """The generator, over synthetic observation sets rather than over a real run."""

    catalog = conftest._catalog_rules()
    registry = default_registry()
    manual_rule = _first_rule_with_check(
        lambda check: conftest._returns_only_manual_confirmation(registry[check])
    )
    decided_rule = _first_rule_with_check(
        lambda check: not conftest._returns_only_manual_confirmation(registry[check])
    )

    def observed(**overrides: set[str]) -> dict[str, set[str]]:
        base = {
            rule_id: (
                {"manual"}
                if conftest._returns_only_manual_confirmation(registry[check])
                else {"pass", "failure"}
            )
            for rule_id, check in catalog.items()
        }
        base.update(overrides)
        return base

    assert list(conftest._refusals(observed())) == []

    unexercised = observed()
    del unexercised[decided_rule]
    assert [decided_rule in line for line in conftest._refusals(unexercised)] == [True]

    only_green = conftest._refusals(observed(**{decided_rule: {"pass", "manual"}}))
    messages = list(only_green)
    assert len(messages) == 1 and decided_rule in messages[0]
    assert "observed only" in messages[0]

    deciding_manual = conftest._refusals(observed(**{manual_rule: {"manual", "failure"}}))
    messages = list(deciding_manual)
    assert len(messages) == 1 and manual_rule in messages[0]
    assert "only ever defers to a person" in messages[0]


def test_a_pass_alone_is_not_a_decision(recwarn: pytest.WarningsRecorder) -> None:
    """The distinction the whole gate turns on, stated once as a test.

    `pass` and `manual` are what a rule says when it has nothing to report and when it
    declines to report; only `failure` and `warning` are the rule concluding something. A
    `_DECIDED` set that included `pass` would make refusal 2 satisfied by every rule that
    ever ran, which is the vacuity this file exists to prevent.
    """

    del recwarn
    assert frozenset({"failure", "warning"}) == conftest._DECIDED
    assert "pass" not in conftest._DECIDED
    assert "manual" not in conftest._DECIDED
