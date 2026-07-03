.DEFAULT_GOAL := help

PYTHON ?= uv run python
UV ?= uv
PYTEST ?= uv run pytest
PRE_COMMIT ?= uv run pre-commit
DOCKER_COMPOSE ?= docker compose

.PHONY: help setup sync test precommit-install precommit docker-build docker-up docker-logs docker-down clean

help: ## Show available targets.
	@awk 'BEGIN {FS = ":.*## "; printf "Available targets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## Sync the uv development environment.
	$(UV) sync --dev

setup: sync precommit-install ## Sync dependencies and install pre-commit hooks.

test: ## Run the test suite.
	$(PYTEST)

precommit-install: ## Install pre-commit git hooks.
	$(PRE_COMMIT) install

precommit: ## Run pre-commit hooks against all files.
	$(PRE_COMMIT) run --all-files

docker-build: ## Build the Docker Compose services.
	$(DOCKER_COMPOSE) build

docker-up: ## Start Docker Compose services in the background.
	$(DOCKER_COMPOSE) up -d

docker-logs: ## Follow Docker Compose logs.
	$(DOCKER_COMPOSE) logs -f

docker-down: ## Stop Docker Compose services.
	$(DOCKER_COMPOSE) down

clean: ## Remove local test and Python cache files.
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
