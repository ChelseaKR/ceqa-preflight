.DEFAULT_GOAL := help

I18N_LOCALES := src/ceqa_preflight/locales

.PHONY: help install format lint typecheck test security audit schemas i18n i18n-update verify build \
	lock-check \
	audit-sources

help:
	@uv run --locked ceqa-preflight --help

install:
	uv sync --all-groups

# `uv run` without `--locked` performs an implicit sync: with a pyproject.toml edit in the
# tree it re-resolves and rewrites uv.lock in place, and the gate it was running still
# exits 0. Every recipe above and below therefore passes --locked, and this target runs
# first in `verify` so a lockfile that no longer matches pyproject.toml fails before any
# other target can heal it in the working tree. `uv lock --check` resolves and compares;
# it never writes. CI was already protected by its `uv sync --all-groups --locked` step,
# which is exactly why README.md's "CI runs the same `make verify` gate" needed this to
# become true locally too.
lock-check:
	uv lock --check --offline

format:
	uv run --locked ruff format .

lint:
	uv run --locked ruff format --check .
	uv run --locked ruff check .

typecheck:
	uv run --locked mypy src

test:
	uv run --locked pytest --cov=ceqa_preflight --cov-report=term-missing

security:
	uv run --locked bandit -q -r src

audit:
	@attempt=1; while [ $$attempt -le 3 ]; do \
		uv run --locked pip-audit && exit 0; \
		echo "pip-audit attempt $$attempt failed; retrying" >&2; \
		attempt=$$((attempt + 1)); \
		sleep 3; \
	done; exit 1

schemas:
	uv run --locked python -m ceqa_preflight.schema_export

# The four checks docs/I18N.md requires of `make verify`, plus the invariants it implies.
# One Python program rather than a shell pipeline: it regenerates the template and each
# compiled catalog in memory and compares, so the gate writes nothing and cannot quietly
# repair the drift it exists to report, and it behaves the same on every platform. An
# earlier version shelled out to `pybabel` and `cmp` through a POSIX scratch path, which
# the Windows job could not write to.
i18n:
	uv run --locked python scripts/check_i18n.py

# Authoring step, never part of `verify`. Run it after wrapping or rewording a string, then
# `pybabel update -i $(I18N_LOCALES)/messages.pot -d $(I18N_LOCALES) --omit-header` to carry
# a new message into each catalog for translation. See docs/I18N.md.
i18n-update:
	uv run --locked pybabel extract -F babel.cfg --no-location --omit-header \
		-o $(I18N_LOCALES)/messages.pot src
	uv run --locked pybabel compile -d $(I18N_LOCALES) --statistics

# Maintainer-only: checks that rule source citation URLs still resolve. Not part of `verify` —
# it makes real network requests, which the shipped product and CI gate deliberately never do.
audit-sources:
	uv run --locked python3 scripts/check_rule_sources.py

verify: lock-check lint typecheck test security audit i18n

build: verify
	uv build
