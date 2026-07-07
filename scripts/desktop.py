#!/usr/bin/env python3
"""Lighthouse Desktop App.

Spawns the FastAPI backend in a background thread, then initializes a native
macOS WebKit view pointing to the dashboard.
"""

from __future__ import annotations

import os
import sys

import webview

from lighthouse_ai.paths import make_paths
from lighthouse_ai.supervisor import serve_in_thread


def main() -> int:
    # 1. Initialize data paths
    data_dir = os.environ.get("LIGHTHOUSE_DATA_DIR")
    if not data_dir:
        # Default to a user-home state dir for the desktop app
        data_dir = os.path.expanduser("~/.lighthouse")

    paths = make_paths(data_dir)
    paths.ensure()

    # Run migrations
    from lighthouse_ai.schema import kinds_for, migrate_all

    migrate_all(kinds_for(paths))

    # 2. Spin up the FastAPI server in a background thread on a random free port
    server, thread, port = serve_in_thread(paths, port=0)
    print(f"Lighthouse Backend running on http://127.0.0.1:{port}")

    # 3. Create the native desktop Webview
    try:
        # Initialize window with comfortable dimensions matching the design
        webview.create_window(
            title="Lighthouse Research Instrument",
            url=f"http://127.0.0.1:{port}",
            width=1200,
            height=800,
            min_size=(900, 600),
            text_select=True,
            confirm_close=False,
        )

        # Start the GUI loop
        webview.start(debug=False)
    finally:
        # 4. Clean shutdown: trigger server exit and join thread
        print("Shutting down Lighthouse Backend...")
        server.should_exit = True
        thread.join(timeout=5)

    return 0


if __name__ == "__main__":
    sys.exit(main())
