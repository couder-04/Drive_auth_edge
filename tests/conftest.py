"""Shared pytest fixtures for DriveAuth Edge."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _dashboard_test_auth(monkeypatch):
    """Dashboard admin routes require an API key unless insecure mode is set.

    Default test posture: fixed key + helpers can send X-API-Key. Individual
    auth-negative tests override these env vars explicitly.
    """
    monkeypatch.setenv("DRIVEAUTH_DASHBOARD_API_KEY", "test-dashboard-key")
    monkeypatch.delenv("DRIVEAUTH_ALLOW_INSECURE_DASHBOARD", raising=False)


@pytest.fixture()
def admin_headers() -> dict[str, str]:
    return {"X-API-Key": "test-dashboard-key"}
