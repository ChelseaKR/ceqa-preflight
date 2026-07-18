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
	uv run pip-audit

schemas:
	uv run python -m ceqa_preflight.schema_export

verify: lint typecheck test security audit

build: verify
	uv build
