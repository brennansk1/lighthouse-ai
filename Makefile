.PHONY: install dev test lint check pull-models stack-up stack-down init demo clean help

# Default Python environment manager
UV ?= uv

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## Install Lighthouse + runtime deps
	$(UV) pip install -e .

dev:  ## Install Lighthouse + dev/test deps
	$(UV) sync --all-extras

test:  ## Run the full test suite
	$(UV) run pytest -q

lint:  ## Run ruff linter
	$(UV) run ruff check src tests

check:  ## Run linter + test suite (CI equivalent)
	$(MAKE) lint
	$(MAKE) test

pull-models:  ## Pull the required Ollama models
	@echo "Pulling bge-m3 (embeddings, 1.2GB)..."
	ollama pull bge-m3
	@echo "Pulling qwen3:14b (researcher/synthesizer, ~9GB)..."
	ollama pull qwen3:14b
	@echo "Done. Run 'make demo' to start Lighthouse."

stack-up:  ## Start Qdrant + SearXNG via Docker Compose
	docker compose -f scripts/lh-stack.docker-compose.yml up -d
	@echo "Qdrant: http://localhost:6333"
	@echo "SearXNG: http://localhost:8888"

stack-down:  ## Stop Docker stack
	docker compose -f scripts/lh-stack.docker-compose.yml down

init:  ## Initialize Lighthouse data directory
	$(UV) run lighthouse init --no-install-service

demo: stack-up init  ## Start the full stack for a demo
	@echo "Starting supervisor..."
	$(UV) run lighthouse-supervisor &
	@sleep 2
	@echo ""
	@echo "Lighthouse is running at http://localhost:8765"
	@echo "Run: $(UV) run lighthouse research 'your question'"

clean:  ## Remove build artifacts
	rm -rf dist/ .pytest_cache/ __pycache__/ src/lighthouse_ai.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
