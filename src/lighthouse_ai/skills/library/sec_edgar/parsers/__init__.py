"""SEC EDGAR filing parsers — deterministic, pure-Python, no network.

Provides Item-section extractors for 10-K filings:

* :func:`parse_10k_item_1a` — extract Item 1A (Risk Factors)
* :func:`parse_10k_item_7`  — extract Item 7 (Management's Discussion and
  Analysis of Financial Condition and Results of Operations)

Both parsers operate on plain text or lightly-stripped HTML; they use
deterministic regex-based header detection and require no network access.
"""

from .item_sections import parse_10k_item_1a, parse_10k_item_7

__all__ = ["parse_10k_item_1a", "parse_10k_item_7"]
