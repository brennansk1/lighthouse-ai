"""RSS / Atom feed skill — user-added feed monitoring and fetch.

Promotes the platform's ``sources/rss.py`` adapter into a full watchable
skill. Supports any RSS 2.0 or Atom 1.0 feed URL that the platform egress
allowlist permits. Per-feed grade and bias-rating are set at registration.

All network access goes through SkillContext primitives; the import guard
enforces that this package never touches httpx/requests/urllib directly.
"""
