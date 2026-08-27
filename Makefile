.DEFAULT_GOAL := help

I18N_LOCALES := src/ceqa_preflight/locales
I18N_TAGS := en es
# The gate regenerates into a scratch path and compares. It never writes into the tree, so
# running `make verify` cannot quietly repair the very drift it is supposed to report.
I18N_SCRATCH := $(shell printf '%s' "$${TMPDIR:-/tmp}")/ceqa-preflight-i18n

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

# The four checks docs/I18N.md requires of `make verify`. Extraction freshness and catalog
# compilation are expressed as "regenerate into scratch, then compare", so a wrapped string
# that never reached a catalog, or a `.po` edit that never reached its `.mo`, fails here
# instead of reaching a reader as silent English. `scripts/check_i18n.py` owns key parity,
# placeholder parity, BCP 47 validity, the English-identity invariant, and a second,
# format-independent check that each compiled catalog still says what its source says.
#
# Byte comparison is only sound because every `.po` pins a complete header, including
# POT-Creation-Date. Babel invents that field when a catalog omits it, using the wall
# clock, which would make this gate fail on a clean tree.
i18n:
	uv run pybabel extract -F babel.cfg --no-location --omit-header \
		-o $(I18N_SCRATCH).pot src
	cmp $(I18N_SCRATCH).pot $(I18N_LOCALES)/messages.pot
	@for tag in $(I18N_TAGS); do \
		echo "checking compiled catalog: $$tag"; \
		uv run pybabel compile --locale $$tag \
			--input-file $(I18N_LOCALES)/$$tag/LC_MESSAGES/messages.po \
			--output-file $(I18N_SCRATCH)-$$tag.mo || exit 1; \
		cmp $(I18N_SCRATCH)-$$tag.mo $(I18N_LOCALES)/$$tag/LC_MESSAGES/messages.mo || exit 1; \
	done
	uv run python scripts/check_i18n.py

# Authoring step, never part of `verify`. Run it after wrapping or rewording a string, then
# `pybabel update -i $(I18N_LOCALES)/messages.pot -d $(I18N_LOCALES) --omit-header` to carry
# a new message into each catalog for translation. See docs/I18N.md.
i18n-update:
	uv run pybabel extract -F babel.cfg --no-location --omit-header \
		-o $(I18N_LOCALES)/messages.pot src
	uv run pybabel compile -d $(I18N_LOCALES) --statistics

# Maintainer-only: checks that rule source citation URLs still resolve. Not part of `verify` —
# it makes real network requests, which the shipped product and CI gate deliberately never do.
audit-sources:
	uv run python3 scripts/check_rule_sources.py

verify: lint typecheck test security audit i18n

build: verify
	uv build
