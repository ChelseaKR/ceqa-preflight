.DEFAULT_GOAL := help

.PHONY: help install format lint typecheck test security audit schemas verify build

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

verify: lint typecheck test security audit

build: verify
	uv build
