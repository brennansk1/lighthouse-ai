"""LLM / embedding backend adapters.

Each backend exposes a small, uniform surface used by the Gateway and the
RAG embedder: ``chat`` for completion, ``embed`` for vector embedding.
Backends are *optional* — every adapter advertises ``.available()`` so the
caller can fall back when the underlying service isn't running.
"""

from .ollama import OllamaBackend, OllamaUnavailable

__all__ = ["OllamaBackend", "OllamaUnavailable"]
