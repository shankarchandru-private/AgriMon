"""Starts AgriMon: python -m agrimon  (then open http://127.0.0.1:8000)."""

from __future__ import annotations

from pathlib import Path

import uvicorn

from agrimon.api.app import create_app
from agrimon.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    settings = load_settings(ROOT)
    app = create_app(settings)
    print(f"AgriMon running on http://{settings.server.host}:{settings.server.port}")
    uvicorn.run(app, host=settings.server.host, port=settings.server.port, log_level="warning")


if __name__ == "__main__":
    main()
