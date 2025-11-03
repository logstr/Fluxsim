.PHONY: install lint format format-check typecheck test coverage check clean

VENV ?= .venv

install:
	python3 -m venv $(VENV)
	. $(VENV)/bin/activate && \
		pip install --upgrade pip && \
		pip install -e .[dev]

lint:
	ruff check .
	black --check .
	mypy fluxsim

format:
	ruff format .
	black .

format-check:
	ruff format --check .
	black --check .

typecheck:
	mypy fluxsim

test:
	pytest --maxfail=1 --disable-warnings -q

coverage:
	pytest --cov=fluxsim --cov-report=term --cov-report=xml

check: lint test

clean:
	rm -rf .pytest_cache .coverage coverage.xml
