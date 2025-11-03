.PHONY: install lint format format-check typecheck test coverage check clean

VENV ?= .venv
LINT_PATHS ?= fluxsim tests

install:
	python3 -m venv $(VENV)
	. $(VENV)/bin/activate && \
		pip install --upgrade pip && \
		pip install -e .[dev]

lint:
	ruff check $(LINT_PATHS)
	black --check $(LINT_PATHS)

format:
	ruff format $(LINT_PATHS)
	black $(LINT_PATHS)

format-check:
	ruff format --check $(LINT_PATHS)
	black --check $(LINT_PATHS)

typecheck:
	mypy fluxsim

test:
	pytest --maxfail=1 --disable-warnings -q

coverage:
	pytest --cov=fluxsim --cov-report=term --cov-report=xml

check: lint test

clean:
	rm -rf .pytest_cache .coverage coverage.xml
