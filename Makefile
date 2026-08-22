.DEFAULT_GOAL := help

.PHONY: help install format lint typecheck test security audit schemas verify build audit-sources \
	i18n-extract i18n-update i18n-compile i18n-check

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

# Maintainer-only: checks that rule source citation URLs still resolve. Not part of `verify` —
# it makes real network requests, which the shipped product and CI gate deliberately never do.
audit-sources:
	uv run python3 scripts/check_rule_sources.py

# i18n seam (docs/I18N.md). Re-extract after adding or editing an `_()` call, then commit the
# updated POT and, if translations changed, run i18n-compile and commit the .mo files too.
i18n-extract:
	uv run pybabel extract -F babel.cfg -o src/ceqa_preflight/locales/ceqa_preflight.pot \
		--project ceqa-preflight --copyright-holder "CEQA Preflight contributors" \
		--msgid-bugs-address https://github.com/ChelseaKR/ceqa-preflight/issues \
		--no-location --sort-output src

# Merge new/changed msgids from the POT into each locale's .po, preserving existing
# translations. Run this after i18n-extract when a string's source text (not just its
# presence) changed; new strings still need a human translation before i18n-compile.
i18n-update: i18n-extract
	uv run pybabel update -i src/ceqa_preflight/locales/ceqa_preflight.pot \
		-d src/ceqa_preflight/locales -D ceqa_preflight --previous

i18n-compile:
	uv run pybabel compile -d src/ceqa_preflight/locales -D ceqa_preflight

# Enforces docs/I18N.md's `make verify` obligations: POT freshness, EN/ES key and
# placeholder parity, BCP 47 locale validity, and that committed .mo files match their .po.
i18n-check:
	uv run python3 scripts/check_i18n.py

verify: lint typecheck test security audit i18n-check

build: verify
	uv build
