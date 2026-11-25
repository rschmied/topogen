UV ?= uv

.DEFAULT_GOAL := help

.PHONY: help sync lint format format-check typecheck check test build clean distclean

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z_-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## Install runtime and development dependencies
	$(UV) sync --dev --locked

lint: ## Run Ruff lint checks
	$(UV) run ruff check

format: ## Format source files with Ruff
	$(UV) run ruff format
	$(UV) run ruff check --fix

format-check: ## Check formatting without changing files
	$(UV) run ruff format --check

typecheck: ## Run ty static type checks
	$(UV) run ty check src

test: sync ## Run unit tests
	$(UV) run pytest --cov=src/topogen --cov-report=term-missing --cov-report=xml

check: lint format-check typecheck test ## Run all static checks

build: clean ## Build source and wheel distributions
	$(UV) build

clean: ## Remove generated build and cache files
	rm -rf build dist .ruff_cache .pytest_cache .coverage coverage.xml htmlcov
	find src -type d -name __pycache__ -prune -exec rm -rf {} +
	find src -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

distclean: clean ## Also remove the project virtual environment
	rm -rf .venv
