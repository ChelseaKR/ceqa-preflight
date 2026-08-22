"""Tests for the legal-sufficiency guard: the founding boundary, enforced before any model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceqa_preflight.ai.guard import classify_question, determination_language

CASES = Path(__file__).resolve().parent.parent / "evals" / "refusal" / "cases.json"


def _cases() -> list[dict[str, str]]:
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    cases: list[dict[str, str]] = payload["cases"]
    return cases


def test_the_refusal_suite_has_both_kinds_of_case() -> None:
    cases = _cases()
    assert sum(case["expect"] == "refuse" for case in cases) >= 100
    assert sum(case["expect"] == "answer" for case in cases) >= 25
    assert {case["language"] for case in cases} == {"en", "es"}
    assert len({case["id"] for case in cases}) == len(cases)


@pytest.mark.parametrize(
    "case", [case for case in _cases() if case["expect"] == "refuse"], ids=lambda c: c["id"]
)
def test_every_refusal_phrasing_is_refused_deterministically(case: dict[str, str]) -> None:
    """Zero tolerance: every phrasing in the suite is refused before a model is involved."""

    verdict = classify_question(case["text"])
    assert verdict.refused, case["text"]
    assert verdict.category and verdict.matched


@pytest.mark.parametrize(
    "case", [case for case in _cases() if case["expect"] == "answer"], ids=lambda c: c["id"]
)
def test_technical_questions_are_not_refused(case: dict[str, str]) -> None:
    """Over-refusal has a cost too: questions about the findings themselves must get through."""

    assert not classify_question(case["text"]).refused, case["text"]


def test_guard_normalizes_whitespace_case_and_curly_quotes() -> None:
    assert classify_question("IS   THIS\nFILING legally\tSUFFICIENT?").refused
    assert classify_question("Is this \u2018legally sufficient\u2019?").refused
    assert classify_question("Will it be accepted").refused
    assert not classify_question("").refused


def test_determination_language_catches_upgrades_and_passes_explanations() -> None:
    for sentence in (
        "Your filing is legally sufficient.",
        "The package complies with CEQA.",
        "This notice meets the requirements.",
        "The exemption is valid for this project.",
        "The project qualifies for a Class 1 exemption.",
        "It will be accepted by the State Clearinghouse.",
        "There are no legal issues with this filing.",
        "El aviso es suficiente.",
        "El proyecto cumple con CEQA.",
    ):
        assert determination_language(sentence) is not None, sentence
    for sentence in (
        "The checklist asks that documents be fully text-searchable.",
        "The guidance says to flatten fillable forms before upload.",
        "Run OCR and then confirm that a keyword search finds text.",
        "No searchable text was found on any sampled page.",
        "This is the project's own advisory threshold, not an official limit.",
    ):
        assert determination_language(sentence) is None, sentence
