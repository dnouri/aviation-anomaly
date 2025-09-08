.PHONY: help install test test-unit test-integration typecheck format lint fix-whitespace check clean generate-test-data validate-sql

# Default target
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo "Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
	@echo ""
	@echo "Examples:"
	@echo "  make install       # Install all dependencies"
	@echo "  make test          # Run all tests in parallel"
	@echo "  make test-unit     # Run only fast unit tests"
	@echo "  make format        # Auto-format code"
	@echo "  make check         # Run all checks (fix-whitespace, format, typecheck, lint)"

install: ## Install project and dev dependencies
	@echo "Installing dependencies..."
	uv sync --dev
	@echo "Installing pre-commit hooks..."
	uv run pre-commit install
	@echo "✓ Installation complete"

test: ## Run all tests with pytest in parallel
	@echo "Running all tests..."
	PYTHONPATH=. uv run pytest tests/ -v -n auto
	@echo "✓ All tests passed"

test-unit: ## Run only unit tests (fast)
	@echo "Running unit tests..."
	PYTHONPATH=. uv run pytest tests/ -v -n auto -m "not integration"
	@echo "✓ Unit tests passed"

test-integration: ## Run only integration tests
	@echo "Running integration tests..."
	PYTHONPATH=. uv run pytest tests/ -v -m integration
	@echo "✓ Integration tests passed"

typecheck: ## Run type checking with mypy
	@echo "Running type checks..."
	uv run mypy . --exclude 'research.*' --exclude 'tmp'
	@echo "✓ Type checking passed"

format: ## Auto-format code with ruff
	@echo "Formatting code..."
	uv run ruff format .
	uv run ruff check --fix .
	@echo "✓ Code formatted"

lint: ## Run linting with ruff (no auto-fix)
	@echo "Linting code..."
	uv run ruff check .
	@echo "✓ Linting passed"

fix-whitespace: ## Fix trailing whitespace and missing newlines at EOF
	@echo "Fixing whitespace issues..."
	@# Remove trailing whitespace from Python files (portable sed -i usage)
	@find . -name "*.py" -type f -exec sed -i.bak 's/[[:space:]]*$$//' {} \; -exec rm {}.bak \;
	@# Add newline at end of file if missing
	@find . -name "*.py" -type f -exec sh -c 'tail -c1 {} | read -r _ || echo >> {}' \;
	@# Also fix Makefile, README, and TOML files
	@for ext in md toml; do \
		find . -name "*.$$ext" -type f -exec sed -i.bak 's/[[:space:]]*$$//' {} \; -exec rm {}.bak \; ; \
		find . -name "*.$$ext" -type f -exec sh -c 'tail -c1 {} | read -r _ || echo >> {}' \; ; \
	done
	@echo "✓ Whitespace fixed"

check: fix-whitespace format typecheck lint ## Run all checks (format, fix-whitespace, typecheck, lint)
	@echo "✓ All checks passed"

clean: ## Clean up generated files and caches
	@echo "Cleaning up..."
	@rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name ".coverage" -delete 2>/dev/null || true
	@echo "✓ Cleanup complete"

generate-test-data: ## Generate test data fixtures for SQL testing
	@echo "Generating test data..."
	uv run python -m aviation_anomaly.generate_test_data
	@echo "✓ Test data generated in tests/data/"

validate-sql: ## Validate SQL syntax in sql/ directory
	@echo "Validating SQL files..."
	uv run python -m aviation_anomaly.validate_sql
	@echo "✓ SQL validation complete"
