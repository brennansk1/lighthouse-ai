# Contributing to Lighthouse

We welcome contributions to Lighthouse! Whether you are fixing bugs, improving the React dashboard, or adding new RAG skills, this document outlines the process to help you get started quickly.

## Developer Environment Setup

Lighthouse uses `uv` as the exclusive dependency and package manager to guarantee deterministic builds.

1. **Install uv:**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. **Clone and Sync:**
   ```bash
   git clone https://github.com/<your-org>/lighthouse.git
   cd lighthouse
   uv sync
   ```
3. **Dependencies:** Make sure you have Ollama installed and the required models pulled if you are testing the backend execution paths:
   ```bash
   ollama pull qwen3:14b
   ollama pull bge-m3
   ```

## Code Quality Standards

Lighthouse is built to strict professional standards. All code must pass the static analysis gates before being merged.

### 1. Formatting and Linting (Ruff)
We use `ruff` to enforce PEP 8 style guidelines and instantly catch linting errors.
```bash
# Auto-format code
uv run ruff format .

# Check for linting errors and automatically fix safe ones
uv run ruff check --fix .
```

### 2. Type Checking (Mypy)
We use strict static typing. Ensure your changes pass the type checker:
```bash
uv run mypy src scripts
```

### 3. Testing (Pytest)
Every feature and fix must be accompanied by tests. We aim to maintain our 3,200+ test coverage invariant.
```bash
# Run the entire test suite (mocked/offline)
uv run pytest

# Run a specific file
uv run pytest tests/test_your_feature.py
```

## Making a Pull Request

1. Fork the repository and create your branch from `main`.
2. Write tests for any new behavior or bug fix.
3. Ensure the test suite, `ruff`, and `mypy` all pass locally.
4. Push your branch and open a Pull Request.
5. Provide a clear description of the problem your PR solves and verify it against the `docs/BUILD_MANIFEST.md` contracts if applicable.

Thank you for helping us make Lighthouse the best open-source, local-first research instrument!
