"""Lighthouse TUI — a Textual terminal dashboard, parity with the webapp.

Entry point: ``lighthouse tui`` → :func:`lighthouse_ai.tui.app.main`.
"""

from .client import LighthouseClient

__all__ = ["LighthouseClient"]
