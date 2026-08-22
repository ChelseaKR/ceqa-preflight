"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from ceqa_preflight.i18n import DEFAULT_LOCALE, set_locale


@pytest.fixture(autouse=True)
def _reset_locale() -> Iterator[None]:
    """Reset the process-wide active locale around every test.

    ``ceqa_preflight.i18n`` tracks the active locale as module state, set once at the CLI
    boundary per real invocation. In the test process that state persists across tests unless
    reset, so a test that exercises a non-default locale (or the CLI's ``--locale`` option)
    could otherwise leak it into an unrelated test that runs after it.
    """

    set_locale(DEFAULT_LOCALE)
    yield
    set_locale(DEFAULT_LOCALE)
