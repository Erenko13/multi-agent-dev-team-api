from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import set_session_manager
from src.api.routes import router
from src.api.sessions import SessionManager
from src.config import load_config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    manager = SessionManager(config)
    set_session_manager(manager)
    logger.info("SessionManager initialized")
    yield
    await manager.shutdown()
    logger.info("SessionManager shut down")


app = FastAPI(
    title="Multi-Agent Dev Team API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


def main() -> None:
    """Entry point for `devteam-api` script."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "src.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
