"""Wikipedia-specific parsers — deterministic, pure-Python, no network."""

from .infobox import parse_infobox

__all__ = ["parse_infobox"]
