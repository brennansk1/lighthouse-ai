#!/usr/bin/env bash
# Local quality gate: mirrors the CI pipeline.
# Run from the repo root. Needs +x: chmod +x scripts/check.sh
set -euo pipefail

echo "==> ruff check"
uv run ruff check src tests

# mypy is non-blocking for now: the codebase isn't fully typed yet.
echo "==> mypy (non-fatal)"
uv run mypy src/lighthouse_ai || echo "mypy reported issues (non-blocking)"

echo "==> pytest"
uv run pytest -q
