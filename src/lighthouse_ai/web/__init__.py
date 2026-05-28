"""Lighthouse web dashboard — mounts the design-as-code bundle and a small
JSON API for live data (so the React MOCK can be swapped for real values).

The HTML/JSX/CSS bundle is the Claude Design handoff from
``lighthouse/project/`` — preserved verbatim. The React app loads from CDN
(react, react-dom, @babel/standalone). We just serve the static files and
expose ``/api/dashboard`` to back the same shape as the MOCK in
``home-shared.jsx``.
"""

from .routes import attach_web

__all__ = ["attach_web"]
