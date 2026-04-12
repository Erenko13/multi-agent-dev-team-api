from __future__ import annotations

import logging
import logging.handlers
import os
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


def _setup_logging(log_dir: str = "logs") -> None:
    """Configure logging to stdout and a rotating log file."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "devteam.log")

    formatter = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — 5 MB per file, keep last 5 files
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # suppress noisy LLM HTTP logs


def main() -> None:
    """Entry point for `devteam-api` script."""
    import uvicorn

    _setup_logging()
    uvicorn.run(
        "src.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_config=None,  # use our logging config instead of uvicorn's default
    )


if __name__ == "__main__":
    main()
