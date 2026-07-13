from __future__ import annotations

import logging
import os

import uvicorn

from .app import create_app
from .config import WebConfig


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = WebConfig.from_env()
    app = create_app(config, initial_admin_password=os.environ.get("SYLO_ADMIN_PASSWORD"))
    uvicorn.run(app, host=config.bind_host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
