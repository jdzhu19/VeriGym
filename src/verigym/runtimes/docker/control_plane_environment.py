"""Fail-closed environment construction for the trusted host Codex control plane."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

_FORWARDED_PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY")
_SYNTHESIZED_BYPASS_NAMES = ("NO_PROXY", "no_proxy")
_MANDATORY_LOOPBACK_BYPASS = ("localhost", "127.0.0.1", "::1")
_IGNORED_HOST_PROXY_NAMES = (
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "ALL_PROXY",
    "all_proxy",
)
_REDACTION_PROXY_NAMES = (
    *_FORWARDED_PROXY_NAMES,
    "NO_PROXY",
    *_IGNORED_HOST_PROXY_NAMES,
)
_MAX_NO_PROXY_BYTES = 64 * 1024
_MAX_NO_PROXY_ENTRY_BYTES = 4096


class ControlPlaneEnvironmentError(RuntimeError):
    """A values-free failure raised before the trusted host process starts."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class TrustedHostAppServerEnvironment:
    """In-memory process environment plus a values-free persistent identity."""

    values: dict[str, str]
    proxy_forwarding_enabled: bool
    forwarded_proxy_environment_names: tuple[str, ...]
    synthesized_control_plane_environment_names: tuple[str, ...]
    mandatory_loopback_bypass_present: bool
    redaction_values: tuple[str, ...]

    def safe_identity(self) -> dict[str, object]:
        return {
            "proxy_forwarding_enabled": self.proxy_forwarding_enabled,
            "forwarded_proxy_environment_names": list(self.forwarded_proxy_environment_names),
            "synthesized_control_plane_environment_names": list(
                self.synthesized_control_plane_environment_names
            ),
            "mandatory_loopback_bypass_present": (self.mandatory_loopback_bypass_present),
            "proxy_values_persisted_or_hashed": False,
        }


def build_trusted_host_app_server_environment(
    *,
    allow_proxy_environment: bool,
    forwarded_proxy_environment_names: Sequence[str],
    broker_url: str,
    source: Mapping[str, str] | None = None,
) -> TrustedHostAppServerEnvironment:
    """Build the only environment allowed for the trusted host app-server."""

    source_environment = os.environ if source is None else source
    _require_loopback_broker(broker_url)
    environment = {
        "PATH": source_environment.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    if "HOME" not in source_environment:
        raise ControlPlaneEnvironmentError(
            "control_plane_environment_unavailable",
            "inherited Codex login requires HOME",
        )
    environment["HOME"] = source_environment["HOME"]
    if "CODEX_HOME" in source_environment:
        environment["CODEX_HOME"] = source_environment["CODEX_HOME"]
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "TMPDIR"):
        if name in source_environment:
            environment[name] = source_environment[name]

    requested_set = set(forwarded_proxy_environment_names)
    if len(requested_set) != len(forwarded_proxy_environment_names) or not requested_set <= set(
        _FORWARDED_PROXY_NAMES
    ):
        raise ControlPlaneEnvironmentError(
            "control_plane_proxy_policy_mismatch",
            "trusted host proxy forwarding is outside its strict allowlist",
        )
    requested_names = tuple(name for name in _FORWARDED_PROXY_NAMES if name in requested_set)
    present_names = tuple(name for name in _FORWARDED_PROXY_NAMES if name in source_environment)
    if allow_proxy_environment:
        if requested_names != present_names:
            raise ControlPlaneEnvironmentError(
                "control_plane_proxy_identity_changed",
                "trusted host proxy-name identity changed before process launch",
            )
        for name in present_names:
            environment[name] = source_environment[name]
        effective_bypass = _effective_loopback_bypass(source_environment.get("NO_PROXY"))
        environment["NO_PROXY"] = effective_bypass
        environment["no_proxy"] = effective_bypass
        synthesized_names: tuple[str, ...] = _SYNTHESIZED_BYPASS_NAMES
    else:
        if requested_names:
            raise ControlPlaneEnvironmentError(
                "control_plane_proxy_policy_mismatch",
                "trusted host proxy forwarding is disabled",
            )
        synthesized_names = ()

    bypass_present = (
        not allow_proxy_environment
        or _mandatory_loopback_bypass_present(environment.get("NO_PROXY", ""))
        and environment.get("NO_PROXY") == environment.get("no_proxy")
    )
    if not bypass_present:
        raise ControlPlaneEnvironmentError(
            "control_plane_loopback_bypass_unavailable",
            "mandatory trusted host loopback proxy bypass could not be guaranteed",
        )
    forbidden_names = set(_IGNORED_HOST_PROXY_NAMES) - {"no_proxy"}
    if forbidden_names.intersection(environment):
        raise ControlPlaneEnvironmentError(
            "control_plane_proxy_policy_mismatch",
            "trusted host process environment contains a forbidden proxy name",
        )
    return TrustedHostAppServerEnvironment(
        values=environment,
        proxy_forwarding_enabled=allow_proxy_environment,
        forwarded_proxy_environment_names=(present_names if allow_proxy_environment else ()),
        synthesized_control_plane_environment_names=synthesized_names,
        mandatory_loopback_bypass_present=bypass_present,
        redaction_values=_redaction_values(source_environment, environment),
    )


def _require_loopback_broker(broker_url: str) -> None:
    try:
        parsed = urlsplit(broker_url)
        port = parsed.port
    except ValueError as exc:
        raise ControlPlaneEnvironmentError(
            "control_plane_broker_identity_invalid",
            "trusted host broker URL is invalid",
        ) from exc
    if (
        parsed.scheme != "ws"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
    ):
        raise ControlPlaneEnvironmentError(
            "control_plane_broker_identity_invalid",
            "trusted host broker must use an uncredentialed loopback WebSocket URL",
        )


def _effective_loopback_bypass(host_no_proxy: str | None) -> str:
    raw = host_no_proxy or ""
    encoded = raw.encode("utf-8")
    if len(encoded) > _MAX_NO_PROXY_BYTES or any(
        ord(character) < 32 or ord(character) == 127 for character in raw
    ):
        raise ControlPlaneEnvironmentError(
            "control_plane_loopback_bypass_unavailable",
            "host NO_PROXY cannot be safely extended",
        )
    entries: list[str] = []
    seen: set[str] = set()
    for candidate in raw.split(","):
        entry = candidate.strip()
        if not entry:
            continue
        if len(entry.encode("utf-8")) > _MAX_NO_PROXY_ENTRY_BYTES:
            raise ControlPlaneEnvironmentError(
                "control_plane_loopback_bypass_unavailable",
                "host NO_PROXY contains an oversized entry",
            )
        normalized = entry.casefold()
        if normalized not in seen:
            entries.append(entry)
            seen.add(normalized)
    for mandatory in _MANDATORY_LOOPBACK_BYPASS:
        normalized = mandatory.casefold()
        if normalized not in seen:
            entries.append(mandatory)
            seen.add(normalized)
    effective = ",".join(entries)
    if len(effective.encode("utf-8")) > _MAX_NO_PROXY_BYTES:
        raise ControlPlaneEnvironmentError(
            "control_plane_loopback_bypass_unavailable",
            "effective NO_PROXY exceeds its trusted host bound",
        )
    if not _mandatory_loopback_bypass_present(effective):
        raise ControlPlaneEnvironmentError(
            "control_plane_loopback_bypass_unavailable",
            "effective NO_PROXY is missing a mandatory loopback identity",
        )
    return effective


def _mandatory_loopback_bypass_present(value: str) -> bool:
    entries = {entry.strip().casefold() for entry in value.split(",") if entry.strip()}
    return all(mandatory.casefold() in entries for mandatory in _MANDATORY_LOOPBACK_BYPASS)


def _redaction_values(
    source: Mapping[str, str],
    environment: Mapping[str, str],
) -> tuple[str, ...]:
    values = {value for name in _REDACTION_PROXY_NAMES for value in (source.get(name),) if value}
    values.update(
        value
        for name in (*_FORWARDED_PROXY_NAMES, *_SYNTHESIZED_BYPASS_NAMES)
        for value in (environment.get(name),)
        if value
    )
    return tuple(sorted(values, key=len, reverse=True))


__all__ = [
    "ControlPlaneEnvironmentError",
    "TrustedHostAppServerEnvironment",
    "build_trusted_host_app_server_environment",
]
