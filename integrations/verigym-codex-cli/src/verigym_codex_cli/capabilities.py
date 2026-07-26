"""Zero-model-call Codex CLI capability discovery and sealing."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .process import CodexCliProcessRunner, ExecutableIdentity, resolve_executable
from .util import redact_text, stable_hash

_MAX_REPORT_BYTES = 1024 * 1024
_KNOWN_SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
_KNOWN_APPROVAL_MODES = ("untrusted", "on-failure", "on-request", "never")
_CACHE: dict[str, CapabilityReport] = {}


class CapabilityError(RuntimeError):
    """The installed CLI cannot support the required conformance protocol."""


@dataclass(frozen=True)
class CapabilityReport:
    schema_version: str
    executable_name: str
    executable_sha256: str
    version_output: str
    normalized_help: str
    normalized_exec_help: str
    machine_output_flag: str
    non_interactive_command: str
    model_flag: str
    ephemeral_flag: str
    sandbox_flag: str
    approval_flag: str | None
    config_flag: str
    skip_git_flag: str
    strict_config_flag: str
    ignore_user_config_flag: str
    ignore_rules_flag: str
    stdin_prompt_supported: bool
    supported_sandbox_modes: tuple[str, ...]
    supported_approval_modes: tuple[str, ...]
    selected_event_protocol: str
    selected_invocation_protocol: str
    capability_fingerprint: str
    diagnostic_process_count: int
    model_call_count: int

    def safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "executable_name": self.executable_name,
            "executable_sha256": self.executable_sha256,
            "version_output": self.version_output,
            "normalized_help": self.normalized_help,
            "normalized_exec_help": self.normalized_exec_help,
            "machine_output_flag": self.machine_output_flag,
            "non_interactive_command": self.non_interactive_command,
            "model_flag": self.model_flag,
            "ephemeral_flag": self.ephemeral_flag,
            "sandbox_flag": self.sandbox_flag,
            "approval_flag": self.approval_flag,
            "config_flag": self.config_flag,
            "skip_git_flag": self.skip_git_flag,
            "strict_config_flag": self.strict_config_flag,
            "ignore_user_config_flag": self.ignore_user_config_flag,
            "ignore_rules_flag": self.ignore_rules_flag,
            "stdin_prompt_supported": self.stdin_prompt_supported,
            "supported_sandbox_modes": list(self.supported_sandbox_modes),
            "supported_approval_modes": list(self.supported_approval_modes),
            "selected_event_protocol": self.selected_event_protocol,
            "selected_invocation_protocol": self.selected_invocation_protocol,
            "capability_fingerprint": self.capability_fingerprint,
            "diagnostic_process_count": self.diagnostic_process_count,
            "model_call_count": self.model_call_count,
        }


def discover_capabilities(
    executable: ExecutableIdentity | None = None,
    *,
    force: bool = False,
) -> tuple[ExecutableIdentity, CapabilityReport]:
    identity = executable or resolve_executable()
    if not force and identity.sha256 in _CACHE:
        return identity, _CACHE[identity.sha256]
    runner = CodexCliProcessRunner(identity, max_output_bytes=2 * 1024 * 1024)
    with tempfile.TemporaryDirectory(prefix="verigym-codex-doctor-") as temporary:
        cwd = Path(temporary)
        version = runner.run(["--version"], cwd=cwd, timeout_s=15.0)
        help_result = runner.run(["--help"], cwd=cwd, timeout_s=15.0)
        exec_help = runner.run(["exec", "--help"], cwd=cwd, timeout_s=15.0)
    for label, result in (
        ("--version", version),
        ("--help", help_result),
        ("exec --help", exec_help),
    ):
        if result.timed_out or result.exit_code != 0 or result.stdout_truncated:
            raise CapabilityError(f"Codex {label} diagnostic did not complete safely")
    version_output = _single_output(version.stdout, version.stderr)
    normalized_help = _normalize_help(help_result.stdout + "\n" + help_result.stderr)
    normalized_exec_help = _normalize_help(exec_help.stdout + "\n" + exec_help.stderr)
    combined = f"{normalized_help}\n{normalized_exec_help}"
    machine_flag = _required_flag(normalized_exec_help, "--json", "machine-readable JSONL")
    model_flag = _first_flag(normalized_exec_help, ("--model", "-m"))
    ephemeral_flag = _required_flag(normalized_exec_help, "--ephemeral", "ephemeral sessions")
    sandbox_flag = _first_flag(normalized_exec_help, ("--sandbox", "-s"))
    config_flag = _first_flag(combined, ("--config", "-c"))
    skip_git_flag = _required_flag(
        normalized_exec_help,
        "--skip-git-repo-check",
        "non-project working directories",
    )
    strict_config_flag = _required_flag(
        normalized_exec_help,
        "--strict-config",
        "strict configuration validation",
    )
    ignore_user_config_flag = _required_flag(
        normalized_exec_help,
        "--ignore-user-config",
        "user configuration isolation",
    )
    ignore_rules_flag = _required_flag(
        normalized_exec_help,
        "--ignore-rules",
        "exec-policy rule isolation",
    )
    approval_flag = (
        "--ask-for-approval"
        if "--ask-for-approval" in normalized_exec_help
        else "-a"
        if _contains_short_flag(normalized_exec_help, "-a")
        else None
    )
    sandbox_modes = tuple(mode for mode in _KNOWN_SANDBOX_MODES if mode in normalized_exec_help)
    if "read-only" not in sandbox_modes or "workspace-write" not in sandbox_modes:
        raise CapabilityError(
            "Codex CLI lacks required read-only and workspace-write sandbox modes"
        )
    approval_modes = tuple(mode for mode in _KNOWN_APPROVAL_MODES if mode in combined)
    stdin_supported = "stdin" in normalized_exec_help.lower() and (
        "prompt" in normalized_exec_help.lower() or "instructions" in normalized_exec_help.lower()
    )
    if not stdin_supported:
        raise CapabilityError("Codex CLI does not document the required stdin prompt protocol")
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "executable_name": identity.name,
        "executable_sha256": identity.sha256,
        "version_output": version_output,
        "normalized_help": normalized_help,
        "normalized_exec_help": normalized_exec_help,
        "machine_output_flag": machine_flag,
        "non_interactive_command": "exec",
        "model_flag": model_flag,
        "ephemeral_flag": ephemeral_flag,
        "sandbox_flag": sandbox_flag,
        "approval_flag": approval_flag,
        "config_flag": config_flag,
        "skip_git_flag": skip_git_flag,
        "strict_config_flag": strict_config_flag,
        "ignore_user_config_flag": ignore_user_config_flag,
        "ignore_rules_flag": ignore_rules_flag,
        "stdin_prompt_supported": True,
        "supported_sandbox_modes": sandbox_modes,
        "supported_approval_modes": approval_modes,
        "selected_event_protocol": "codex-exec-jsonl-v1",
        "selected_invocation_protocol": "codex-exec-stdin-v1",
        "diagnostic_process_count": 3,
        "model_call_count": 0,
    }
    payload["capability_fingerprint"] = stable_hash(payload)
    report = _report_from_dict(payload)
    _CACHE[identity.sha256] = report
    return identity, report


def runtime_capabilities() -> tuple[ExecutableIdentity, CapabilityReport]:
    identity = resolve_executable()
    sealed = os.environ.get("VERIGYM_CODEX_CAPABILITY_FILE")
    if sealed:
        return identity, load_capability_report(Path(sealed), identity)
    return discover_capabilities(identity)


def load_capability_report(
    path: Path,
    executable: ExecutableIdentity,
) -> CapabilityReport:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise CapabilityError("sealed Codex capability report is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > _MAX_REPORT_BYTES
    ):
        raise CapabilityError("sealed Codex capability report is unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CapabilityError("sealed Codex capability report is malformed") from exc
    if not isinstance(payload, dict):
        raise CapabilityError("sealed Codex capability report must be an object")
    report = _report_from_dict(payload)
    if report.executable_sha256 != executable.sha256 or report.executable_name != executable.name:
        raise CapabilityError(
            "sealed Codex capability report does not match the selected executable"
        )
    _CACHE[executable.sha256] = report
    return report


def _report_from_dict(payload: dict[str, Any]) -> CapabilityReport:
    try:
        fingerprint = str(payload["capability_fingerprint"])
        unsigned = dict(payload)
        unsigned.pop("capability_fingerprint", None)
        if fingerprint != stable_hash(unsigned):
            raise CapabilityError("Codex capability fingerprint is invalid")
        report = CapabilityReport(
            schema_version=str(payload["schema_version"]),
            executable_name=str(payload["executable_name"]),
            executable_sha256=str(payload["executable_sha256"]),
            version_output=str(payload["version_output"]),
            normalized_help=str(payload["normalized_help"]),
            normalized_exec_help=str(payload["normalized_exec_help"]),
            machine_output_flag=str(payload["machine_output_flag"]),
            non_interactive_command=str(payload["non_interactive_command"]),
            model_flag=str(payload["model_flag"]),
            ephemeral_flag=str(payload["ephemeral_flag"]),
            sandbox_flag=str(payload["sandbox_flag"]),
            approval_flag=(str(payload["approval_flag"]) if payload.get("approval_flag") else None),
            config_flag=str(payload["config_flag"]),
            skip_git_flag=str(payload["skip_git_flag"]),
            strict_config_flag=str(payload["strict_config_flag"]),
            ignore_user_config_flag=str(payload["ignore_user_config_flag"]),
            ignore_rules_flag=str(payload["ignore_rules_flag"]),
            stdin_prompt_supported=payload["stdin_prompt_supported"] is True,
            supported_sandbox_modes=tuple(str(item) for item in payload["supported_sandbox_modes"]),
            supported_approval_modes=tuple(
                str(item) for item in payload["supported_approval_modes"]
            ),
            selected_event_protocol=str(payload["selected_event_protocol"]),
            selected_invocation_protocol=str(payload["selected_invocation_protocol"]),
            capability_fingerprint=fingerprint,
            diagnostic_process_count=int(payload["diagnostic_process_count"]),
            model_call_count=int(payload["model_call_count"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, CapabilityError):
            raise
        raise CapabilityError("Codex capability report has an invalid schema") from exc
    if (
        report.schema_version != "1.0"
        or report.model_call_count != 0
        or not report.stdin_prompt_supported
        or report.machine_output_flag != "--json"
        or report.non_interactive_command != "exec"
        or report.strict_config_flag != "--strict-config"
        or report.ignore_user_config_flag != "--ignore-user-config"
        or report.ignore_rules_flag != "--ignore-rules"
        or "read-only" not in report.supported_sandbox_modes
        or "workspace-write" not in report.supported_sandbox_modes
    ):
        raise CapabilityError("Codex capability report does not satisfy conformance requirements")
    return report


def _single_output(stdout: str, stderr: str) -> str:
    text = redact_text(stdout.strip() or stderr.strip())[:4096]
    if not text:
        raise CapabilityError("Codex --version returned no version identity")
    return text


def _normalize_help(text: str) -> str:
    lines = []
    for raw in redact_text(text).splitlines():
        line = " ".join(raw.strip().split())
        if not line:
            continue
        lowered = line.lower()
        if any(
            token in lowered
            for token in (
                "--json",
                "--model",
                "--ephemeral",
                "--sandbox",
                "--ask-for-approval",
                "--config",
                "--skip-git-repo-check",
                "--strict-config",
                "--ignore-user-config",
                "--ignore-rules",
                "stdin",
                "prompt",
                "read-only",
                "workspace-write",
                "danger-full-access",
                "on-request",
                "on-failure",
                "untrusted",
                "never",
            )
        ):
            lines.append(line)
    return "\n".join(dict.fromkeys(lines))[: 256 * 1024]


def _required_flag(help_text: str, flag: str, capability: str) -> str:
    if flag not in help_text:
        raise CapabilityError(f"Codex CLI lacks required {capability} support")
    return flag


def _first_flag(help_text: str, flags: tuple[str, ...]) -> str:
    for flag in flags:
        if flag.startswith("--") and flag in help_text:
            return flag
        if _contains_short_flag(help_text, flag):
            return flag
    raise CapabilityError(f"Codex CLI lacks required flag family: {'/'.join(flags)}")


def _contains_short_flag(help_text: str, flag: str) -> bool:
    return any(
        line.startswith(flag + " ")
        or line.startswith(flag + ",")
        or f" {flag} " in line
        or f" {flag}," in line
        for line in help_text.splitlines()
    )


def clear_capability_cache() -> None:
    _CACHE.clear()


__all__ = [
    "CapabilityError",
    "CapabilityReport",
    "clear_capability_cache",
    "discover_capabilities",
    "load_capability_report",
    "runtime_capabilities",
]
