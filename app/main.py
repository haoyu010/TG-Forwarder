from __future__ import annotations

import uvicorn

from app.api import create_app
from app.config import load_config
from app.runtime import build_worker
from app.storage import EventRepository


config = load_config()
repository = EventRepository(config.database_path)
worker = build_worker(config, repository)
app = create_app(config=config, repository=repository, worker=worker)


def main() -> None:
    uvicorn.run("app.main:app", host=config.dashboard.host, port=config.dashboard.port, reload=False)


if __name__ == "__main__":
    main()
