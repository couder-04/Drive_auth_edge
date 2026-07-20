# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-07-21

### Added

- Dashboard admin authentication (`DRIVEAUTH_DASHBOARD_API_KEY`, Bearer / X-API-Key).
- Thread-safe dashboard state via FastAPI lifespan / `app.state` (no module-level `_auth` cache).
- `scripts/bootstrap.py` for Stage-1 model setup + Stage-2 visibility (no silent fallback).
- `scripts/stress_test.py` soak harness with RSS/CPU sampling and graceful shutdown.
- Versioned OpenAPI export (`docs/openapi/`, `scripts/export_openapi.py`).
- Open-source docs: CONTRIBUTING, SECURITY, CHANGELOG, Code of Conduct, issue/PR templates.
- Makefile targets: `install`, `bootstrap`, `test`, `lint`, `coverage`, `demo`, `openapi`, `stress`.
- Matcher / fusion / risk edge-case tests; CI coverage gate + artifacts.

### Changed

- Real matcher load fails closed when voice/face are not ready unless
  `DRIVEAUTH_USE_MOCK=1` or `DRIVEAUTH_ALLOW_MOCK_FALLBACK=1`.
- CI runs ruff, pytest with coverage threshold, dependency cache, and failure summaries.

### Security

- Mutating dashboard endpoints (purge, enroll, fraud, reset, profile, authenticate, …)
  require admin credentials by default.

## [0.2.0] — prior

Pre-MVP engineering baseline (Trust/Risk pipeline, ladder, dashboard, hardware stubs).
