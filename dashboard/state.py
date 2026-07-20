"""Thread-safe dashboard application state (replaces module-level singletons)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from driveauth import DriveAuth


@dataclass
class DashboardState:
    """Per-app cache for the loaded DriveAuth instance."""

    auth: DriveAuth | None = None
    auth_key: tuple[str, str, bool] | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def clear(self) -> None:
        with self.lock:
            self.auth = None
            self.auth_key = None
