"""Dev-only: serve just the Lighthouse control plane (dashboard + API), no
supervisor daemons. For local UI verification. Data dir via LIGHTHOUSE_DATA_DIR.
"""
import os

import uvicorn

from lighthouse_ai.controlplane import create_app
from lighthouse_ai.paths import make_paths
from lighthouse_ai.schema import kinds_for, migrate_all

paths = make_paths(os.environ["LIGHTHOUSE_DATA_DIR"])
paths.ensure()
migrate_all(kinds_for(paths))
app = create_app(paths)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
