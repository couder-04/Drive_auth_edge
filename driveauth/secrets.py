"""Pluggable secrets loading for DriveAuth Edge.

Default remains ``secrets.env`` via :class:`EnvFileSecretsProvider` (identical
to pre-hardening behaviour). Optional :class:`VaultSecretsProvider` talks to
HashiCorp Vault KV v2 through a swappable HTTP client.
:class:`HSMSecretsProvider` is an explicit stub — real HSM hardware is required
before that path can return secrets; the stub exists so integrators can wire
the interface without pretending the gap is closed.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

logger = logging.getLogger("driveauth.secrets")

# Keys whose values must never appear in logs (name substrings, uppercased).
_SECRET_NAME_MARKERS = (
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "TOKEN",
    "API_KEY",
    "APIKEY",
    "PRIVATE_KEY",
    "PRIVATEKEY",
    "CREDENTIAL",
    "BIO_KEY",
)

_LOADED = False
_PROVIDER = None  # SecretsProvider | None; set after Protocol is defined


@runtime_checkable
class SecretsProvider(Protocol):
    """Resolve a secret by name. Returns ``None`` when the key is absent."""

    def get(self, key: str) -> str | None: ...


def is_sensitive_secret_name(name: str) -> bool:
    """True when ``name`` looks like a secret that must never be logged."""
    upper = (name or "").upper()
    return any(marker in upper for marker in _SECRET_NAME_MARKERS)


def _default_secrets_path() -> Path:
    override = os.getenv("DRIVEAUTH_SECRETS_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # Repo root (parent of driveauth/)
    return Path(__file__).resolve().parents[1] / "secrets.env"


def _parse_env_file(secrets_path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Never logs values."""
    out: dict[str, str] = {}
    for raw in secrets_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if not key:
            continue
        out[key] = val
    return out


class EnvFileSecretsProvider:
    """Today's behaviour: ``secrets.env`` (or ``DRIVEAUTH_SECRETS_FILE``).

    On construction (or :meth:`load`), values are merged into ``os.environ``
    unless the variable is already set and non-empty (unless ``override=True``).
    :meth:`get` reads from the in-memory map first, then ``os.environ``.
    """

    def __init__(
        self,
        *,
        path: Path | None = None,
        override: bool = False,
        load_on_init: bool = True,
    ):
        self._path = path or _default_secrets_path()
        self._override = override
        self._cache: dict[str, str] = {}
        self._loaded = False
        if load_on_init:
            self.load()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Path | None:
        """Load the env file into cache + ``os.environ``. Returns path or None."""
        if not self._path.is_file():
            # Log path only — never invent or echo values.
            logger.debug("secrets file not found: %s", self._path)
            self._loaded = True
            return None

        parsed = _parse_env_file(self._path)
        count = 0
        for key, val in parsed.items():
            self._cache[key] = val
            if not self._override and key in os.environ and os.environ[key] != "":
                continue
            os.environ[key] = val
            count += 1
        # Count/path only — never secret values.
        logger.info("Loaded %d secret(s) from %s", count, self._path)
        self._loaded = True
        return self._path

    def get(self, key: str) -> str | None:
        if not self._loaded:
            self.load()
        # Existing non-empty env wins (same rule as load_secrets / legacy get_secret).
        env_val = os.getenv(key)
        if env_val is not None and env_val != "":
            return env_val
        if key in self._cache:
            val = self._cache[key]
            return val if val != "" else None
        return None


# Type for an injectable Vault HTTP client: (method, url, headers, body) -> (status, body_text)
VaultHttpClient = Callable[
    [str, str, dict[str, str], bytes | None],
    tuple[int, str],
]


def _default_vault_http(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return int(resp.status), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return int(exc.code), payload


class VaultSecretsProvider:
    """HashiCorp Vault KV v2 reader with a swappable HTTP client.

    Defaults to ``urllib`` against ``DRIVEAUTH_VAULT_ADDR`` /
    ``DRIVEAUTH_VAULT_TOKEN`` / ``DRIVEAUTH_VAULT_MOUNT`` /
    ``DRIVEAUTH_VAULT_PATH``. Pass ``http_client`` in tests or to wrap
    ``hvac`` / cloud SDKs behind the same interface.

    This closes the *plumbing* gap (no secrets in the image). It does **not**
    close operational gaps: Vault policy, network trust, and token rotation
    remain deployer responsibilities.
    """

    def __init__(
        self,
        *,
        addr: str | None = None,
        token: str | None = None,
        mount: str | None = None,
        path: str | None = None,
        http_client: VaultHttpClient | None = None,
        cache: dict[str, str] | None = None,
    ):
        self._addr = (addr or os.getenv("DRIVEAUTH_VAULT_ADDR", "")).rstrip("/")
        self._token = token if token is not None else os.getenv("DRIVEAUTH_VAULT_TOKEN", "")
        self._mount = (mount or os.getenv("DRIVEAUTH_VAULT_MOUNT", "secret")).strip("/")
        self._path = (path or os.getenv("DRIVEAUTH_VAULT_PATH", "driveauth")).strip("/")
        self._http = http_client or _default_vault_http
        self._cache: dict[str, str] = dict(cache or {})
        self._fetched = False

    def _fetch_all(self) -> None:
        if self._fetched:
            return
        self._fetched = True
        if not self._addr or not self._token:
            logger.warning(
                "VaultSecretsProvider: DRIVEAUTH_VAULT_ADDR/TOKEN missing; "
                "get() will return None"
            )
            return
        url = f"{self._addr}/v1/{self._mount}/data/{self._path}"
        headers = {
            "X-Vault-Token": self._token,
            "Accept": "application/json",
        }
        try:
            status, body = self._http("GET", url, headers, None)
        except Exception as exc:
            # Exception type only — never token / body.
            logger.error(
                "VaultSecretsProvider: request failed (%s)",
                type(exc).__name__,
            )
            return
        if status != 200:
            logger.error(
                "VaultSecretsProvider: HTTP %s from Vault (path=%s)",
                status,
                self._path,
            )
            return
        try:
            payload = json.loads(body)
            data = payload.get("data", {}).get("data", {})
            if isinstance(data, dict):
                for k, v in data.items():
                    if v is None:
                        continue
                    self._cache[str(k)] = str(v)
            # Count only.
            logger.info(
                "VaultSecretsProvider: cached %d key(s) from mount=%s path=%s",
                len(self._cache),
                self._mount,
                self._path,
            )
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            logger.error(
                "VaultSecretsProvider: bad response JSON (%s)",
                type(exc).__name__,
            )

    def get(self, key: str) -> str | None:
        self._fetch_all()
        val = self._cache.get(key)
        if val is None or val == "":
            # Fall back to process env so non-Vault keys still work.
            env_val = os.getenv(key)
            return env_val if env_val else None
        return val


class HSMSecretsProvider:
    """Stub for hardware-security-module backed secrets.

    Construction succeeds so integrators can select the provider via config.
    :meth:`get` always raises until a real HSM backend is injected via
    ``backend``. Code alone cannot close the HSM gap — see
    ``docs/key-provisioning.md``.
    """

    def __init__(self, *, backend: SecretsProvider | None = None):
        self._backend = backend

    def get(self, key: str) -> str | None:
        if self._backend is not None:
            return self._backend.get(key)
        raise RuntimeError(
            "HSMSecretsProvider has no backend: wire a real HSM client "
            "(PKCS#11 / vendor SDK) or keep EnvFileSecretsProvider / "
            "VaultSecretsProvider. See docs/key-provisioning.md."
        )


def build_secrets_provider(
    kind: str | None = None,
    *,
    env_file_path: Path | None = None,
    vault_http_client: VaultHttpClient | None = None,
    hsm_backend: SecretsProvider | None = None,
) -> SecretsProvider:
    """Factory. ``kind`` defaults to ``DRIVEAUTH_SECRETS_PROVIDER`` or ``env``."""
    selected = (kind or os.getenv("DRIVEAUTH_SECRETS_PROVIDER", "env")).strip().lower()
    if selected in ("", "env", "envfile", "file"):
        return EnvFileSecretsProvider(path=env_file_path)
    if selected in ("vault", "hashicorp", "hashicorp_vault"):
        return VaultSecretsProvider(http_client=vault_http_client)
    if selected in ("hsm", "pkcs11"):
        return HSMSecretsProvider(backend=hsm_backend)
    raise ValueError(
        f"Unknown DRIVEAUTH_SECRETS_PROVIDER={selected!r}; "
        "use env|vault|hsm"
    )


def set_secrets_provider(provider: SecretsProvider | None) -> None:
    """Replace the process-global provider (tests / late reconfiguration)."""
    global _PROVIDER, _LOADED
    _PROVIDER = provider
    _LOADED = provider is not None


def get_secrets_provider() -> SecretsProvider:
    """Return the configured provider, constructing the default if needed."""
    global _PROVIDER, _LOADED
    if _PROVIDER is None:
        _PROVIDER = build_secrets_provider()
        _LOADED = True
    return _PROVIDER


def load_secrets(*, path: Path | None = None, override: bool = False) -> Path | None:
    """Parse KEY=VALUE lines into ``os.environ`` (legacy entry point).

    Existing environment variables win unless ``override=True``.
    Returns the path loaded, or ``None`` if the file is missing.
    Always installs an :class:`EnvFileSecretsProvider` as the process provider.
    """
    global _LOADED, _PROVIDER
    provider = EnvFileSecretsProvider(
        path=path,
        override=override,
        load_on_init=False,
    )
    result = provider.load()
    _PROVIDER = provider
    _LOADED = True
    return result


def ensure_secrets_loaded() -> None:
    if not _LOADED:
        # Honour DRIVEAUTH_SECRETS_PROVIDER when first touching secrets.
        get_secrets_provider()


def get_secret(name: str, default: str = "") -> str:
    ensure_secrets_loaded()
    provider = get_secrets_provider()
    val = provider.get(name)
    if val is None or val == "":
        return default
    return val


def openrouter_configured() -> bool:
    return bool(get_secret("OPENROUTER_API_KEY").strip())


def google_maps_key() -> str:
    return get_secret("GOOGLE_MAPS_API_KEY").strip()
