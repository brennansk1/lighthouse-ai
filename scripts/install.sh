#!/usr/bin/env bash
# Lighthouse install script
# Usage: curl -fsSL https://raw.githubusercontent.com/brennansk1/lighthouse-ai/main/scripts/install.sh | sh
set -e

REPO="brennansk1/lighthouse-ai"
MIN_PYTHON="3.11"

echo "🔦 Lighthouse installer"
echo "========================"

# Check Python version
python_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
required="3.11"
if [ "$(printf '%s\n' "$required" "$python_version" | sort -V | head -n1)" != "$required" ]; then
  echo "❌ Python $MIN_PYTHON+ required (found $python_version)"
  exit 1
fi
echo "✓ Python $python_version"

# Check ollama
if ! command -v ollama &>/dev/null; then
  echo ""
  echo "Ollama not found. Install it first:"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "  brew install ollama"
  else
    echo "  curl -fsSL https://ollama.ai/install.sh | sh"
  fi
  echo ""
  echo "Then re-run this script."
  exit 1
fi
echo "✓ Ollama $(ollama --version 2>/dev/null | head -1)"

# Install
echo ""
echo "Installing lighthouse-ai..."
if command -v uv &>/dev/null; then
  uv pip install lighthouse-ai
else
  pip install lighthouse-ai
fi

# Init
echo ""
echo "Initializing Lighthouse..."
lighthouse init --no-install-service

echo ""
echo "✅ Lighthouse installed!"
echo ""
echo "Next steps:"
echo "  1. Pull models:     ollama pull bge-m3 && ollama pull qwen3:14b"
echo "  2. Start:           lighthouse-supervisor &"
echo "  3. Open dashboard:  open http://localhost:8765"
echo "  4. Research:        lighthouse research 'your question here'"
echo ""
echo "Full docs: https://github.com/$REPO"
