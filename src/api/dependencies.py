from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.api.sessions import SessionManager

_session_manager: SessionManager | None = None


def set_session_manager(manager: SessionManager) -> None:
    global _session_manager
    _session_manager = manager


def get_session_manager() -> SessionManager:
    if _session_manager is None:
        raise RuntimeError("SessionManager not initialized")
    return _session_manager
