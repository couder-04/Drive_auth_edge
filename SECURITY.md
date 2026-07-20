# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.x     | Yes       |
| 0.x     | Best-effort (pre-MVP) |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email the maintainers with:

- Affected component (dashboard API, matcher, audit log, key storage, …)
- Reproduction steps / PoC (non-destructive preferred)
- Impact assessment (confidentiality / integrity / availability)
- Your preferred contact for coordination

We aim to acknowledge within **72 hours** and provide a remediation plan or
mitigation guidance as soon as practical.

## Security assumptions

Product security boundaries, fail-closed behavior, and explicit non-claims are
documented in [docs/security-assumptions.md](docs/security-assumptions.md).

## Hardening notes (MVP)

- Dashboard admin routes require `DRIVEAUTH_DASHBOARD_API_KEY`.
- Bind the dashboard to `127.0.0.1` unless you terminate TLS and auth at an edge proxy.
- Never commit `secrets.env`, `.bio_key`, or enrolled `*.enc` templates.
- Prefer `DRIVEAUTH_REQUIRE_STAGE2=1` in production builds so missing ONNX heads fail closed.
- Audit log hash-chain verify: `GET /api/audit/verify`.
