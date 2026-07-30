.PHONY: install run lint format typecheck test audit lock lock-check check

install:
	python3.12 -m venv .venv
	.venv/bin/python -m pip install -e '.[dev]'

run:
	.venv/bin/uvicorn repo_steward.app:app --reload

lint:
	.venv/bin/ruff check .

format:
	.venv/bin/ruff format .

typecheck:
	.venv/bin/mypy

test:
	.venv/bin/pytest

audit:
	.venv/bin/pip-audit

lock:
	.venv/bin/uv pip compile --generate-hashes --strip-extras --output-file=requirements.lock pyproject.toml

lock-check:
	.venv/bin/uv pip compile --generate-hashes --strip-extras --output-file=requirements.lock pyproject.toml
	git diff --exit-code -- requirements.lock

check: lint typecheck test audit
