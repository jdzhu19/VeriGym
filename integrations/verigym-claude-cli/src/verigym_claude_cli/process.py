"""Safe host-side Claude CLI process execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

from .events import ProviderTokenMonitor
from .util import redact_text

_SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
_PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
_AUTH_NAMES = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
_MAX_MCP_OUTPUT_TOKENS = 512 * 1024
_TEST_NAMES = ("VERIGYM_FAKE_CLAUDE_SCENARIO", "VERIGYM_FAKE_CLAUDE_LOG")


class ClaudeProcessError(RuntimeError):
    """A safe Claude process-boundary failure."""


@dataclass(frozen=True)
class ExecutableIdentity:
    path: Path
    name: str
    sha256: str
    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class ClaudeProcessResult:
    arguments: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    process_group_cleaned: bool
    broker_cancelled: bool = False
    provider_cancelled: bool = False
    provider_limit_failure: str | None = None
    observed_provider_input_tokens: int | None = None
    observed_provider_output_tokens: int | None = None
    observed_provider_cache_creation_input_tokens: int | None = None
    observed_provider_cache_read_input_tokens: int | None = None
    observed_provider_billed_tokens: int | None = None
    stream_monitor_failed: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def resolve_executable(raw: str | None = None) -> ExecutableIdentity:
    requested = raw or os.environ.get("VERIGYM_CLAUDE_BINARY") or "claude"
    if not requested or "\x00" in requested:
        raise ClaudeProcessError("Claude executable selection is invalid")
    located = shutil.which(requested)
    if located is None:
        raise ClaudeProcessError("Claude executable is unavailable")
    path = Path(located).resolve(strict=True)
    metadata = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
        raise ClaudeProcessError("Claude executable is not a regular executable file")
    return ExecutableIdentity(
        path=path,
        name=path.name,
        sha256=sha256_file(path),
        device=metadata.st_dev,
        inode=metadata.st_ino,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
    )


def configured_broker_root() -> Path:
    raw = os.environ.get("VERIGYM_CLAUDE_BROKER_ROOT")
    if raw is None:
        raise ClaudeProcessError(
            "VERIGYM_CLAUDE_BROKER_ROOT must name a short private scratch directory"
        )
    candidate = Path(raw).expanduser()
    candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
    if candidate.is_symlink():
        raise ClaudeProcessError("Claude broker root cannot be a symlink")
    root = candidate.resolve(strict=True)
    metadata = os.lstat(root)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ClaudeProcessError("Claude broker root must be a directory")
    if metadata.st_mode & 0o077:
        raise ClaudeProcessError("Claude broker root must not be accessible by group or others")
    if len(os.fsencode(root)) > 72:
        raise ClaudeProcessError("Claude broker root is too long for a bounded Unix socket path")
    return root


def forwarded_proxy_environment_names(allowed: bool) -> tuple[str, ...]:
    if not allowed:
        return ()
    return tuple(name for name in _PROXY_NAMES if os.environ.get(name))


def provider_auth_environment_name() -> str:
    """Resolve one exact Claude authentication transport without aliasing credentials."""
    present = tuple(name for name in _AUTH_NAMES if os.environ.get(name))
    if not present:
        raise ClaudeProcessError(
            "Claude custom-provider mode requires ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY"
        )
    if len(present) != 1:
        raise ClaudeProcessError(
            "Claude custom-provider authentication is ambiguous; export exactly one credential"
        )
    credential = os.environ[present[0]]
    if len(credential.encode("utf-8")) > 64 * 1024 or any(
        ord(character) < 32 or ord(character) == 127 for character in credential
    ):
        raise ClaudeProcessError("Claude provider credential violates the environment safety bound")
    return present[0]


def provider_base_url() -> str:
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if not base_url:
        raise ClaudeProcessError("Claude custom-provider mode requires ANTHROPIC_BASE_URL")
    if len(base_url.encode("utf-8")) > 4096 or any(
        ord(character) < 32 or ord(character) == 127 for character in base_url
    ):
        raise ClaudeProcessError("ANTHROPIC_BASE_URL violates the environment safety bound")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ClaudeProcessError("ANTHROPIC_BASE_URL must be a credential-free HTTPS URL")
    return base_url


def provider_environment(
    control_root: Path,
    *,
    allow_proxy_environment: bool,
    include_auth: bool,
) -> dict[str, str]:
    environment = {
        "PATH": _SAFE_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(control_root / "home"),
        "XDG_CACHE_HOME": str(control_root / "cache"),
        "TMPDIR": str(control_root / "tmp"),
        "CLAUDE_CODE_EFFORT_LEVEL": "max",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_BUG_COMMAND": "1",
        "DISABLE_ERROR_REPORTING": "1",
        "DISABLE_TELEMETRY": "1",
        # This raises Claude's MCP tool-output allowance above the broker's 512-KiB byte bound.
        # It does not constrain model input, model output, turns, or model calls.
        "MAX_MCP_OUTPUT_TOKENS": str(_MAX_MCP_OUTPUT_TOKENS),
    }
    for directory in ("home", "cache", "tmp"):
        (control_root / directory).mkdir(mode=0o700, exist_ok=True)
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        if name in os.environ:
            environment[name] = os.environ[name]
    if include_auth:
        auth_name = provider_auth_environment_name()
        credential = os.environ[auth_name]
        base_url = provider_base_url()
        environment[auth_name] = credential
        environment["ANTHROPIC_BASE_URL"] = base_url
    for name in forwarded_proxy_environment_names(allow_proxy_environment):
        environment[name] = os.environ[name]
    if os.environ.get("VERIGYM_CLAUDE_TEST_MODE") == "1" and "fake_claude" in os.environ.get(
        "VERIGYM_CLAUDE_BINARY", ""
    ):
        for name in _TEST_NAMES:
            if name in os.environ:
                environment[name] = os.environ[name]
    return environment


class ClaudeCliProcessRunner:
    def __init__(
        self,
        executable: ExecutableIdentity,
        *,
        max_output_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if max_output_bytes < 1024 or max_output_bytes > 16 * 1024 * 1024:
            raise ClaudeProcessError("Claude evidence bound must be between 1 KiB and 16 MiB")
        self.executable = executable
        self.max_output_bytes = max_output_bytes

    def run(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        timeout_s: float,
        stdin_bytes: bytes | None,
        environment: dict[str, str],
        cancellation_event: threading.Event | None = None,
        max_provider_tokens: int | None = None,
    ) -> ClaudeProcessResult:
        if max_provider_tokens is not None and not 1 <= max_provider_tokens <= 100_000_000:
            raise ClaudeProcessError("Claude provider token limit is outside the safety bound")
        self._assert_identity()
        self._validate_arguments(arguments)
        working_directory = cwd.resolve(strict=True)
        if working_directory.is_symlink() or not working_directory.is_dir():
            raise ClaudeProcessError("Claude control working directory is invalid")
        started = time.monotonic()
        timed_out = False
        broker_cancelled = False
        provider_cancelled = False
        provider_limit_failure: str | None = None
        monitor = ProviderTokenMonitor(max_provider_tokens) if max_provider_tokens else None
        monitor_failures: list[str] = []
        with (
            tempfile.TemporaryFile(dir=working_directory) as stdout_file,
            tempfile.TemporaryFile(dir=working_directory) as stderr_file,
        ):
            try:
                process = subprocess.Popen(
                    [str(self.executable.path), *arguments],
                    cwd=working_directory,
                    env=environment,
                    stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=stderr_file,
                    shell=False,
                    text=False,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                raise ClaudeProcessError(
                    f"Claude process launch failed: {type(exc).__name__}"
                ) from exc
            if process.stdout is None:
                self._terminate_group(process)
                raise ClaudeProcessError("Claude stdout pipe was not created")

            def drain_stdout() -> None:
                assert process.stdout is not None
                try:
                    for line in iter(process.stdout.readline, b""):
                        stdout_file.write(line)
                        if monitor is not None:
                            monitor.observe(line)
                except Exception as exc:  # pragma: no cover - defensive pipe failure
                    monitor_failures.append(type(exc).__name__)

            stdout_thread = threading.Thread(
                target=drain_stdout,
                name="verigym-claude-stdout",
                daemon=True,
            )
            stdout_thread.start()
            if stdin_bytes is not None and process.stdin is not None:
                try:
                    process.stdin.write(stdin_bytes)
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            deadline = started + timeout_s
            while process.poll() is None:
                if monitor_failures:
                    self._terminate_group(process)
                    break
                if monitor is not None and monitor.exhausted():
                    provider_cancelled = True
                    provider_limit_failure = "claude_provider_token_limit"
                    self._terminate_group(process)
                    break
                if cancellation_event is not None and cancellation_event.is_set():
                    broker_cancelled = True
                    self._terminate_group(process)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    self._terminate_group(process)
                    break
                try:
                    process.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    continue
            if process.poll() is None:
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._kill_group(process)
                    process.wait()
            stdout_thread.join(timeout=2.0)
            if stdout_thread.is_alive():
                process.stdout.close()
                stdout_thread.join(timeout=1.0)
                monitor_failures.append("stdout_reader_join_timeout")
            group_cleaned = self._cleanup_group(process.pid)
            provider_usage = monitor.snapshot() if monitor is not None else None
            if monitor is not None and monitor.exhausted():
                provider_limit_failure = "claude_provider_token_limit"
            stdout, stdout_truncated = self._read_bounded(stdout_file)
            stderr, stderr_truncated = self._read_bounded(stderr_file)
        self._assert_identity()
        roots = (working_directory,)
        return ClaudeProcessResult(
            arguments=tuple(arguments),
            exit_code=process.returncode,
            stdout=self._redact_output(
                stdout.decode("utf-8", errors="replace"), environment, roots
            ),
            stderr=self._redact_output(
                stderr.decode("utf-8", errors="replace"), environment, roots
            ),
            duration_s=time.monotonic() - started,
            timed_out=timed_out,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            process_group_cleaned=group_cleaned,
            broker_cancelled=broker_cancelled,
            provider_cancelled=provider_cancelled,
            provider_limit_failure=provider_limit_failure,
            observed_provider_input_tokens=(
                provider_usage.input_tokens if provider_usage is not None else None
            ),
            observed_provider_output_tokens=(
                provider_usage.output_tokens if provider_usage is not None else None
            ),
            observed_provider_cache_creation_input_tokens=(
                provider_usage.cache_creation_input_tokens if provider_usage is not None else None
            ),
            observed_provider_cache_read_input_tokens=(
                provider_usage.cache_read_input_tokens if provider_usage is not None else None
            ),
            observed_provider_billed_tokens=(
                provider_usage.billed_tokens if provider_usage is not None else None
            ),
            stream_monitor_failed=bool(monitor_failures),
        )

    @staticmethod
    def _redact_output(
        value: str,
        environment: dict[str, str],
        roots: tuple[Path, ...],
    ) -> str:
        clean = value
        for name in (*_AUTH_NAMES, *_PROXY_NAMES):
            sensitive = environment.get(name)
            if sensitive:
                clean = clean.replace(sensitive, f"<redacted-{name.lower()}>")
                clean = clean.replace(
                    json.dumps(sensitive, ensure_ascii=False)[1:-1],
                    f"<redacted-{name.lower()}>",
                )
        return redact_text(clean, roots=roots)

    def _assert_identity(self) -> None:
        try:
            metadata = os.stat(self.executable.path, follow_symlinks=False)
        except OSError as exc:
            raise ClaudeProcessError("Claude executable disappeared after discovery") from exc
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
            raise ClaudeProcessError("Claude executable identity changed after discovery")

    @staticmethod
    def _validate_arguments(arguments: list[str]) -> None:
        if not arguments or len(arguments) > 64:
            raise ClaudeProcessError("Claude invocation argument count is invalid")
        for argument in arguments:
            if (
                "\x00" in argument
                or len(argument.encode("utf-8")) > 32 * 1024
                or re.search(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", argument)
            ):
                raise ClaudeProcessError("Claude invocation contains an unsafe argument")

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
        return prefix + stream.read(suffix_size), True

    @staticmethod
    def _terminate_group(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    @staticmethod
    def _kill_group(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @staticmethod
    def _cleanup_group(process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            return True
        return True


__all__ = [
    "ClaudeCliProcessRunner",
    "ClaudeProcessError",
    "ClaudeProcessResult",
    "ExecutableIdentity",
    "configured_broker_root",
    "forwarded_proxy_environment_names",
    "provider_auth_environment_name",
    "provider_base_url",
    "provider_environment",
    "resolve_executable",
]
