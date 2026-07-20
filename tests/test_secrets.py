"""Phase A — SecretsProvider + no accidental secret logging."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import pytest

from driveauth import secrets as secrets_mod
from driveauth.secrets import (
    EnvFileSecretsProvider,
    HSMSecretsProvider,
    VaultSecretsProvider,
    build_secrets_provider,
    get_secret,
    is_sensitive_secret_name,
    load_secrets,
    set_secrets_provider,
)


@pytest.fixture(autouse=True)
def _reset_provider(monkeypatch):
    """Isolate process-global provider between tests."""
    set_secrets_provider(None)
    monkeypatch.delenv("DRIVEAUTH_SECRETS_PROVIDER", raising=False)
    monkeypatch.delenv("DRIVEAUTH_SECRETS_FILE", raising=False)
    secrets_mod._LOADED = False
    yield
    set_secrets_provider(None)
    secrets_mod._LOADED = False


def test_env_file_provider_matches_legacy_load(tmp_path: Path, monkeypatch):
    env_file = tmp_path / "secrets.env"
    env_file.write_text(
        "# comment\nOPENROUTER_API_KEY=sk-test-abc\nEMPTY=\nGOOGLE_MAPS_API_KEY=maps-xyz\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    path = load_secrets(path=env_file)
    assert path == env_file
    assert os.environ["OPENROUTER_API_KEY"] == "sk-test-abc"
    assert get_secret("OPENROUTER_API_KEY") == "sk-test-abc"
    assert get_secret("GOOGLE_MAPS_API_KEY") == "maps-xyz"
    assert get_secret("MISSING", "fallback") == "fallback"


def test_env_file_does_not_override_existing_env(tmp_path: Path, monkeypatch):
    env_file = tmp_path / "secrets.env"
    env_file.write_text("OPENROUTER_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")

    load_secrets(path=env_file)
    assert get_secret("OPENROUTER_API_KEY") == "from-env"


def test_build_provider_default_is_env(tmp_path: Path):
    env_file = tmp_path / "secrets.env"
    env_file.write_text("FOO=bar\n", encoding="utf-8")
    p = build_secrets_provider("env", env_file_path=env_file)
    assert isinstance(p, EnvFileSecretsProvider)
    assert p.get("FOO") == "bar"
    assert p.get("NOPE") is None


def test_vault_provider_with_injected_http_client():
    calls: list[tuple[str, str]] = []

    def fake_http(method, url, headers, body):
        calls.append((method, url))
        assert headers["X-Vault-Token"] == "s.token"
        # Must not appear in our assertions as logged values elsewhere.
        payload = {
            "data": {
                "data": {
                    "OPENROUTER_API_KEY": "vault-sk",
                    "GOOGLE_MAPS_API_KEY": "vault-maps",
                }
            }
        }
        return 200, json.dumps(payload)

    provider = VaultSecretsProvider(
        addr="https://vault.example:8200",
        token="s.token",
        mount="secret",
        path="driveauth/vehicle1",
        http_client=fake_http,
    )
    assert provider.get("OPENROUTER_API_KEY") == "vault-sk"
    assert provider.get("GOOGLE_MAPS_API_KEY") == "vault-maps"
    assert provider.get("ABSENT") is None
    assert calls and calls[0][0] == "GET"
    assert "/v1/secret/data/driveauth/vehicle1" in calls[0][1]
    # Second get should not re-fetch.
    assert provider.get("OPENROUTER_API_KEY") == "vault-sk"
    assert len(calls) == 1


def test_vault_provider_selected_via_factory(monkeypatch):
    monkeypatch.setenv("DRIVEAUTH_SECRETS_PROVIDER", "vault")

    def fake_http(method, url, headers, body):
        return 200, json.dumps({"data": {"data": {"X": "1"}}})

    p = build_secrets_provider(
        vault_http_client=fake_http,
    )
    assert isinstance(p, VaultSecretsProvider)
    # Without addr/token, get falls through / returns None for missing.
    assert p.get("X") is None  # fetch skipped → empty cache


def test_hsm_stub_raises_without_backend():
    p = HSMSecretsProvider()
    with pytest.raises(RuntimeError, match="no backend"):
        p.get("ANY_KEY")


def test_hsm_with_injected_backend():
    class FakeBackend:
        def get(self, key: str) -> str | None:
            return "hsm-value" if key == "K" else None

    p = build_secrets_provider("hsm", hsm_backend=FakeBackend())
    assert isinstance(p, HSMSecretsProvider)
    assert p.get("K") == "hsm-value"
    assert p.get("other") is None


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown"):
        build_secrets_provider("s3-bucket")


def test_load_secrets_never_logs_values(tmp_path: Path, caplog, monkeypatch):
    env_file = tmp_path / "secrets.env"
    secret_val = "sk-super-secret-should-not-appear"
    env_file.write_text(f"OPENROUTER_API_KEY={secret_val}\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with caplog.at_level(logging.DEBUG, logger="driveauth.secrets"):
        load_secrets(path=env_file)

    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert secret_val not in blob
    assert "Loaded 1 secret" in blob or "Loaded 1 secret(s)" in blob


def test_is_sensitive_secret_name():
    assert is_sensitive_secret_name("OPENROUTER_API_KEY")
    assert is_sensitive_secret_name("vault_token")
    assert is_sensitive_secret_name("DB_PASSWORD")
    assert not is_sensitive_secret_name("DRIVEAUTH_USE_MOCK")
    assert not is_sensitive_secret_name("OPENROUTER_STT_MODEL")


# Patterns that look like logging a variable that holds a secret value.
_SECRET_IDENT = re.compile(
    r"\b(api_key|password|passwd|token|secret|credential|private_key|bio_key|"
    r"vault_token|openrouter_api_key|google_maps_api_key)\b",
    re.IGNORECASE,
)
_LOGGER_CALL = re.compile(
    r"logger\.(debug|info|warning|error|exception|critical)\s*\(",
    re.IGNORECASE,
)
# Strip quoted / f-string literal text before scanning for identifiers.
_STRING_LIT = re.compile(
    r"('''.*?'''|\"\"\".*?\"\"\"|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|"
    r"f'(?:\\.|[^'\\])*'|f\"(?:\\.|[^\"\\])*\")",
    re.DOTALL,
)


def _logger_args_look_sensitive(line: str) -> bool:
    """True if a logger call appears to pass a secret-named identifier as data."""
    if not _LOGGER_CALL.search(line):
        return False
    # Drop string literals so messages like 'password verify failed' are OK.
    scrubbed = _STRING_LIT.sub('""', line)
    # Anything after the first logger...( that still names a secret is suspicious.
    m = _LOGGER_CALL.search(scrubbed)
    if not m:
        return False
    args_region = scrubbed[m.end() :]
    return bool(_SECRET_IDENT.search(args_region))


def _iter_source_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    files: list[Path] = []
    for folder in ("driveauth", "hardware", "dashboard", "demo"):
        base = root / folder
        if not base.is_dir():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def test_no_accidental_secret_value_logging_in_source():
    """Static grep: new/existing code must not log variables that hold secrets."""
    offenders: list[str] = []
    root = Path(__file__).resolve().parents[1]
    for path in _iter_source_files():
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _logger_args_look_sensitive(line):
                offenders.append(f"{path.relative_to(root)}:{i}: {stripped}")
    assert not offenders, "Possible secret logging:\n" + "\n".join(offenders)
