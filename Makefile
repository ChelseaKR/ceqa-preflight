.DEFAULT_GOAL := help

I18N_LOCALES := src/ceqa_preflight/locales

.PHONY: help install format lint typecheck test security audit schemas i18n i18n-update verify build \
	audit-sources

help:
	@uv run ceqa-preflight --help

install:
	uv sync --all-groups

format:
	uv run ruff format .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy src

test:
	uv run pytest --cov=ceqa_preflight --cov-report=term-missing

security:
	uv run bandit -q -r src

audit:
	@attempt=1; while [ $$attempt -le 3 ]; do \
		uv run pip-audit && exit 0; \
		echo "pip-audit attempt $$attempt failed; retrying" >&2; \
		attempt=$$((attempt + 1)); \
		sleep 3; \
	done; exit 1

schemas:
	uv run python -m ceqa_preflight.schema_export

# The four checks docs/I18N.md requires of `make verify`, plus the invariants it implies.
# One Python program rather than a shell pipeline: it regenerates the template and each
# compiled catalog in memory and compares, so the gate writes nothing and cannot quietly
# repair the drift it exists to report, and it behaves the same on every platform. An
# earlier version shelled out to `pybabel` and `cmp` through a POSIX scratch path, which
# the Windows job could not write to.
i18n:
	uv run python scripts/check_i18n.py

# Authoring step, never part of `verify`. Run it after wrapping or rewording a string: it
# re-extracts the template, carries the change into every catalog, and recompiles. New
# messages arrive untranslated outside `en`, so `make i18n` stays red until a person
# translates them. See docs/I18N.md.
#
# The middle step is scripts/update_catalogs.py rather than `pybabel update`, which cannot
# be run safely here: with `--omit-header` it deletes the header entry outright, and
# without it the header survives but POT-Creation-Date is rewritten from the wall clock.
# Either way it destroys the pin that lets `make i18n` compare the compiled catalogs byte
# for byte. The script's own docstring records the measurement.
i18n-update:
	uv run pybabel extract -F babel.cfg --no-location --omit-header \
		-o $(I18N_LOCALES)/messages.pot src
	uv run python scripts/update_catalogs.py
	uv run pybabel compile -d $(I18N_LOCALES) --statistics

# Maintainer-only: checks that rule source citation URLs still resolve. Not part of `verify` —
# it makes real network requests, which the shipped product and CI gate deliberately never do.
audit-sources:
	uv run python3 scripts/check_rule_sources.py

verify: lint typecheck test security audit i18n

build: verify
	uv build
