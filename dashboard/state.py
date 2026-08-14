"""Thread-safe dashboard application state (replaces module-level singletons)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from driveauth import DriveAuth


@dataclass
class DashboardState:
    """Per-app cache for the loaded DriveAuth instance and admin sessions."""

    auth: DriveAuth | None = None
    auth_key: tuple[str, str, bool] | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    sessions: dict[str, float] = field(default_factory=dict)
    session_lock: threading.Lock = field(default_factory=threading.Lock)

    def clear(self) -> None:
        with self.lock:
            self.auth = None
            self.auth_key = None
        with self.session_lock:
            self.sessions.clear()

    def put_session(self, token: str, expiry: float) -> None:
        with self.session_lock:
            self.sessions[token] = expiry

    def session_valid(self, token: str, now: float) -> bool:
        with self.session_lock:
            expiry = self.sessions.get(token)
            if expiry is None or expiry < now:
                self.sessions.pop(token, None)
                return False
            return True

    def revoke_session(self, token: str) -> None:
        with self.session_lock:
            self.sessions.pop(token, None)
