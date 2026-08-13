"""Shared safe subprocess execution for both Codex CLI integration tracks."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

from .auth import (
    CREDENTIAL_AUTH_MODES,
    INHERITED_CODEX_LOGIN,
    AuthModeError,
    AuthModeResolution,
    ResolvedAuthMode,
    is_resolved_auth_mode,
    resolve_auth_mode,
)
from .util import redact_text, sha256_file

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_TEST_ENVIRONMENT_NAMES = (
    "VERIGYM_FAKE_CODEX_SCENARIO",
    "VERIGYM_FAKE_CODEX_LOG",
)
_PROXY_ENVIRONMENT_ALLOWLIST = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
)
_RUNTIME_PROXY_ENVIRONMENT_ALLOWLIST = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
)
_SAFE_EXECUTABLE_PATH = "/usr/local/bin:/usr/bin:/bin"


class CodexProcessError(RuntimeError):
    """A safe process-boundary error."""


class ExecutableChangedError(CodexProcessError):
    """The selected executable changed after capability discovery."""


@dataclass(frozen=True)
class ExecutableIdentity:
    path: Path
    name: str
    sha256: str
    device: int
    inode: int
    size: int
    mtime_ns: int

    def safe_dict(self) -> dict[str, object]:
        return {
            "executable_name": self.name,
            "executable_sha256": self.sha256,
        }


@dataclass(frozen=True)
class CodexProcessResult:
    arguments: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    process_group_cleaned: bool


def resolve_executable(raw: str | None = None) -> ExecutableIdentity:
    requested = raw or os.environ.get("VERIGYM_CODEX_BINARY") or "codex"
    if "\x00" in requested:
        raise CodexProcessError("Codex executable selection contains a NUL byte")
    located = shutil.which(requested)
    if located is None:
        raise CodexProcessError("Codex executable is unavailable")
    path = Path(located).resolve(strict=True)
    metadata = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
        raise CodexProcessError("Codex executable is not a regular executable file")
    return ExecutableIdentity(
        path=path,
        name=path.name,
        sha256=sha256_file(path),
        device=metadata.st_dev,
        inode=metadata.st_ino,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
    )


class CodexCliProcessRunner:
    """Run one exact executable with bounded output and explicit environment."""

    def __init__(
        self,
        executable: ExecutableIdentity,
        *,
        auth_mode: str | None = None,
        credential_env: str | None = None,
        max_output_bytes: int = 8 * 1024 * 1024,
        allow_proxy_environment: bool = False,
    ) -> None:
        if auth_mode is not None and not is_resolved_auth_mode(auth_mode):
            raise CodexProcessError("unsupported Codex authentication-mode label")
        if credential_env is not None and not _ENVIRONMENT_NAME.fullmatch(credential_env):
            raise CodexProcessError("credential environment name is invalid")
        if max_output_bytes < 1024 or max_output_bytes > 16 * 1024 * 1024:
            raise CodexProcessError("Codex output bound must be between 1 KiB and 16 MiB")
        self.executable = executable
        self.auth_mode = cast(ResolvedAuthMode | None, auth_mode)
        self.credential_env = credential_env
        self.max_output_bytes = max_output_bytes
        self.allow_proxy_environment = allow_proxy_environment

    def run(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        timeout_s: float,
        stdin_bytes: bytes | None = None,
    ) -> CodexProcessResult:
        self._assert_executable_identity()
        self._validate_arguments(arguments)
        working_directory = self._working_directory(cwd)
        environment = self._environment()
        started = time.monotonic()
        timed_out = False
        exit_code: int | None = None
        group_cleaned = True
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    [str(self.executable.path), *arguments],
                    cwd=working_directory,
                    env=environment,
                    stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    text=False,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                raise CodexProcessError(
                    f"Codex process launch failed: {type(exc).__name__}"
                ) from exc
            try:
                process.communicate(input=stdin_bytes, timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_group(process)
                try:
                    process.communicate(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._kill_group(process)
                    process.communicate()
            exit_code = process.returncode
            group_cleaned = self._cleanup_orphans(process.pid)
            stdout, stdout_truncated = self._read_bounded(stdout_file)
            stderr, stderr_truncated = self._read_bounded(stderr_file)
        self._assert_executable_identity()
        stdout_text = self._redact_process_output(stdout.decode("utf-8", errors="replace"))
        stderr_text = self._redact_process_output(stderr.decode("utf-8", errors="replace"))
        return CodexProcessResult(
            arguments=tuple(arguments),
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_s=time.monotonic() - started,
            timed_out=timed_out,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            process_group_cleaned=group_cleaned,
        )

    def _redact_process_output(self, value: str) -> str:
        clean = value
        if self.allow_proxy_environment:
            proxy_values = {
                os.environ[name]
                for name in forwarded_proxy_environment_names(True)
                if os.environ[name]
            }
            for proxy_value in sorted(proxy_values, key=len, reverse=True):
                clean = clean.replace(proxy_value, "<redacted-proxy>")
                json_escaped = json.dumps(proxy_value, ensure_ascii=False)[1:-1]
                clean = clean.replace(json_escaped, "<redacted-proxy>")
        if self.credential_env is not None:
            credential = os.environ.get(self.credential_env)
            if credential:
                clean = clean.replace(credential, "<redacted-credential>")
        return redact_text(clean)

    def _environment(self) -> dict[str, str]:
        environment = {
            "PATH": _SAFE_EXECUTABLE_PATH,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        if "TMPDIR" in os.environ:
            environment["TMPDIR"] = os.environ["TMPDIR"]
        for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        if self.auth_mode == INHERITED_CODEX_LOGIN:
            if "HOME" not in os.environ:
                raise CodexProcessError("inherited Codex login requires HOME")
            environment["HOME"] = os.environ["HOME"]
            if "CODEX_HOME" in os.environ:
                environment["CODEX_HOME"] = os.environ["CODEX_HOME"]
        elif self.auth_mode in CREDENTIAL_AUTH_MODES:
            if self.credential_env is None or self.credential_env not in os.environ:
                raise CodexProcessError("selected Codex authentication environment is unavailable")
            environment[self.credential_env] = os.environ[self.credential_env]
        for name in forwarded_proxy_environment_names(self.allow_proxy_environment):
            environment[name] = os.environ[name]
        if (
            os.environ.get("VERIGYM_CODEX_TEST_MODE") == "1"
            and "fake_codex" in self.executable.name
        ):
            for name in _TEST_ENVIRONMENT_NAMES:
                if name in os.environ:
                    environment[name] = os.environ[name]
        return environment

    def _assert_executable_identity(self) -> None:
        try:
            metadata = os.stat(self.executable.path, follow_symlinks=False)
        except OSError as exc:
            raise ExecutableChangedError(
                "Codex executable disappeared after capability discovery"
            ) from exc
        observed = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            sha256_file(self.executable.path),
        )
        expected = (
            self.executable.device,
            self.executable.inode,
            self.executable.size,
            self.executable.mtime_ns,
            self.executable.sha256,
        )
        if observed != expected:
            raise ExecutableChangedError(
                "Codex executable identity changed after capability discovery"
            )

    @staticmethod
    def _validate_arguments(arguments: list[str]) -> None:
        if not arguments:
            raise CodexProcessError("Codex invocation requires arguments")
        for argument in arguments:
            if (
                "\x00" in argument
                or len(argument.encode("utf-8")) > 16 * 1024
                or any(ord(character) < 32 and character not in {"\t"} for character in argument)
            ):
                raise CodexProcessError("Codex invocation contains an unsafe argument")

    @staticmethod
    def _working_directory(cwd: Path) -> Path:
        resolved = cwd.resolve(strict=True)
        metadata = os.lstat(resolved)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise CodexProcessError("Codex working directory must be a real directory")
        return resolved

    def _read_bounded(self, stream: BinaryIO) -> tuple[bytes, bool]:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        if size <= self.max_output_bytes:
            return stream.read(), False
        prefix_size = self.max_output_bytes // 2
        suffix_size = self.max_output_bytes - prefix_size
        prefix = stream.read(prefix_size)
        stream.seek(-suffix_size, os.SEEK_END)
        suffix = stream.read(suffix_size)
        return prefix + suffix, True

    @staticmethod
    def _terminate_group(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    @staticmethod
    def _kill_group(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    @staticmethod
    def _cleanup_orphans(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return True
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            return True
        return True


def auth_identity_configuration(
    *,
    default_credential_env: str | None = None,
) -> tuple[AuthModeResolution, str | None]:
    try:
        resolution = resolve_auth_mode(
            os.environ.get("VERIGYM_CODEX_AUTH_MODE", INHERITED_CODEX_LOGIN)
        )
    except AuthModeError as exc:
        raise CodexProcessError("VERIGYM_CODEX_AUTH_MODE is unsupported") from exc
    credential_env = default_credential_env
    if resolution.resolved_auth_mode in CREDENTIAL_AUTH_MODES:
        credential_env = credential_env or os.environ.get("VERIGYM_CODEX_CREDENTIAL_ENV")
        if credential_env is None or not _ENVIRONMENT_NAME.fullmatch(credential_env):
            raise CodexProcessError(
                "credential-based Codex authentication requires an explicit environment name"
            )
    return resolution, credential_env


def forwarded_proxy_environment_names(allowed: bool) -> tuple[str, ...]:
    """Return only present, explicitly allowlisted proxy names without values."""

    if not allowed:
        return ()
    return tuple(name for name in _PROXY_ENVIRONMENT_ALLOWLIST if name in os.environ)


def forwarded_runtime_proxy_environment_names(allowed: bool) -> tuple[str, ...]:
    """Return only provider-transport proxy names for the trusted app-server."""

    if not allowed:
        return ()
    return tuple(name for name in _RUNTIME_PROXY_ENVIRONMENT_ALLOWLIST if name in os.environ)


def auth_configuration(
    *,
    default_credential_env: str | None = None,
) -> tuple[str, str | None]:
    """Return the resolved execution mode using the pre-patch tuple shape."""

    resolution, credential_env = auth_identity_configuration(
        default_credential_env=default_credential_env
    )
    return resolution.resolved_auth_mode, credential_env


__all__ = [
    "CodexCliProcessRunner",
    "CodexProcessError",
    "CodexProcessResult",
    "ExecutableChangedError",
    "ExecutableIdentity",
    "auth_configuration",
    "auth_identity_configuration",
    "forwarded_proxy_environment_names",
    "forwarded_runtime_proxy_environment_names",
    "resolve_executable",
]
