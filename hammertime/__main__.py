"""``python -m hammertime`` — start the HTTP server (the ``npm start`` equivalent)."""

from __future__ import annotations

import logging
import os

import uvicorn

from hammertime.config import debug_enabled

# Importing the app opens the SQLite database and loads .env (like index.js).
from hammertime.main import app  # noqa: E402


def main() -> None:
    port = int(os.environ.get("PORT") or 3000)

    # Keep the console as quiet as the Node server: one startup line, plus SSE logs
    # when DEBUG is set. Uvicorn's access log stays off (Express logs per request).
    logging.basicConfig(
        level=logging.INFO if debug_enabled() else logging.WARNING,
        format="%(message)s",
        force=True,
    )

    print(f"Curling timer backend running on http://localhost:{port}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
