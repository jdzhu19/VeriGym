"""Lightweight trusted local runtime for tests and toy development."""

from __future__ import annotations

import difflib
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from verigym.core.errors import PathPolicyError
from verigym.core.hashing import hash_directory
from verigym.core.workspace import copy_tree_safely, normalize_relative_path
from verigym.public_test_launcher import PublicTestError, execute_public_test
from verigym.runtimes.base import Runtime, RuntimeSession
from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import RuntimeDescriptor
from verigym.schemas.external_agent import ExternalReadOnlyMountIdentity
from verigym.schemas.runtime import SessionSpec, WorkspaceDiff
from verigym.schemas.tool import CommandSpec, CompletedCommand, HealthCheckResult


class LocalRuntimeSession(RuntimeSession):
    """One temporary directory with path checks and bounded subprocess output."""

    def __init__(self, spec: SessionSpec) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix=f"verigym-{spec.label}-")
        self._root = Path(self._temporary.name).resolve()
        self._max_output_bytes = spec.max_output_bytes
        self._closed = False
        self._public_test_invocation_count = 0
        copy_tree_safely(Path(spec.source_dir), self._root)
        self._read_only_temporaries: list[tempfile.TemporaryDirectory[str]] = []
        self._read_only_roots: dict[str, Path] = {}
        self._read_only_identities: list[ExternalReadOnlyMountIdentity] = []
        for mount in spec.read_only_mounts:
            temporary = tempfile.TemporaryDirectory(prefix="verigym-local-readonly-")
            staged = Path(temporary.name).resolve()
            copy_tree_safely(Path(mount.source_dir), staged)
            if hash_directory(staged) != mount.content_hash:
                temporary.cleanup()
                raise PathPolicyError("read-only session asset identity changed while staging")
            self._read_only_temporaries.append(temporary)
            self._read_only_roots[mount.destination] = staged
            self._read_only_identities.append(
                ExternalReadOnlyMountIdentity(
                    destination=mount.destination,
                    content_hash=mount.content_hash,
                    label=mount.label,
                )
            )
        (self._root / ".verigym_internal").mkdir(exist_ok=True)
        self._baseline = self._snapshot()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def external_read_only_mounts(self) -> list[ExternalReadOnlyMountIdentity]:
        return [item.model_copy(deep=True) for item in self._read_only_identities]

    def _resolve(self, raw_path: str, *, allow_root: bool = False) -> Path:
        relative = normalize_relative_path(raw_path, allow_root=allow_root)
        candidate = self._root if relative == "." else self._root / relative
        cursor = self._root
        for part in () if relative == "." else Path(relative).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise PathPolicyError("symlinks are not permitted inside a local session")
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise PathPolicyError("path escapes the runtime session")
        return resolved

    def execute(self, command: CommandSpec) -> CompletedCommand:
        if command.requires_shell:
            raise PathPolicyError("LocalRuntime does not execute shell command strings")
        cwd = self._resolve(command.cwd, allow_root=True)
        if not cwd.is_dir():
            raise PathPolicyError(f"command working directory does not exist: {command.cwd}")
        timeout = command.timeout_s
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(self._root / ".verigym_internal"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        for key, value in command.env.items():
            if "\x00" in key or "\x00" in value or "=" in key:
                raise PathPolicyError("invalid command environment entry")
            environment[key] = value
        started = time.monotonic()
        timed_out = False
        error: str | None = None
        exit_code: int | None = None
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    command.argv,
                    cwd=cwd,
                    env=environment,
                    stdin=subprocess.PIPE if command.stdin is not None else subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    text=False,
                    start_new_session=True,
                )
                try:
                    input_bytes = (
                        command.stdin.encode("utf-8") if command.stdin is not None else None
                    )
                    process.communicate(input=input_bytes, timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
                exit_code = process.returncode
            except FileNotFoundError:
                error = f"executable not found: {command.argv[0]}"
            except OSError as exc:
                error = f"command execution failed: {exc}"
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout_bytes = stdout_file.read(self._max_output_bytes + 1)
            stderr_bytes = stderr_file.read(self._max_output_bytes + 1)
        truncated = (
            len(stdout_bytes) > self._max_output_bytes or len(stderr_bytes) > self._max_output_bytes
        )
        stdout = stdout_bytes[: self._max_output_bytes].decode("utf-8", errors="replace")
        stderr = stderr_bytes[: self._max_output_bytes].decode("utf-8", errors="replace")
        return CompletedCommand(
            argv=command.argv,
            cwd=command.cwd,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=time.monotonic() - started,
            timed_out=timed_out,
            output_truncated=truncated,
            error=error,
        )

    def read_file(self, path: str) -> bytes:
        resolved = self._resolve(path)
        if not resolved.is_file():
            raise FileNotFoundError(path)
        return resolved.read_bytes()

    def write_file(self, path: str, data: bytes) -> None:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(data)

    def execute_public_test(self, test_id: str) -> CompletedCommand:
        self._public_test_invocation_count += 1
        public_root = self._read_only_roots.get("/verigym-public")
        if public_root is None:
            raise PathPolicyError("repository public-test assets are not mounted")
        started = time.monotonic()
        try:
            exit_code, payload, limit = execute_public_test(
                test_id,
                public_root=public_root,
                workspace_root=self._root,
            )
            encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            output_limit = min(limit, self._max_output_bytes)
            truncated = len(encoded) > output_limit
            stdout = encoded[:output_limit].decode("utf-8", errors="replace")
            return CompletedCommand(
                argv=["verigym-public-test", "run", test_id],
                cwd=".",
                exit_code=exit_code,
                stdout=stdout,
                duration_s=time.monotonic() - started,
                output_truncated=truncated,
                runtime_role="agent",
                metadata={
                    "public_test_protocol": "verigym_public_test_v1",
                    "network_policy": "host_local_trusted",
                    "public_assets_read_only": False,
                },
            )
        except PublicTestError as exc:
            return CompletedCommand(
                argv=["verigym-public-test", "run", test_id],
                cwd=".",
                exit_code=None,
                stderr=str(exc),
                duration_s=time.monotonic() - started,
                error=str(exc),
                failure_reason="public_test_contract",
                failure_origin="control_plane",
                runtime_role="agent",
                metadata={
                    "public_test_protocol": "verigym_public_test_v1",
                    "network_policy": "host_local_trusted",
                    "public_assets_read_only": False,
                },
            )

    @property
    def public_test_invocation_count(self) -> int:
        return self._public_test_invocation_count

    def _snapshot(self) -> dict[str, bytes]:
        snapshot: dict[str, bytes] = {}
        for path in sorted(self._root.rglob("*")):
            relative = path.relative_to(self._root)
            if ".verigym_internal" in relative.parts:
                continue
            if path.is_symlink():
                raise PathPolicyError(f"symlink found in workspace: {relative.as_posix()}")
            if path.is_file():
                snapshot[relative.as_posix()] = path.read_bytes()
        return snapshot

    def snapshot_diff(self) -> WorkspaceDiff:
        current = self._snapshot()
        changed = sorted(
            path
            for path in set(self._baseline) | set(current)
            if self._baseline.get(path) != current.get(path)
        )
        parts: list[str] = []
        added = 0
        deleted = 0
        for path in changed:
            before_bytes = self._baseline.get(path, b"")
            after_bytes = current.get(path, b"")
            try:
                before = before_bytes.decode("utf-8").splitlines(keepends=True)
                after = after_bytes.decode("utf-8").splitlines(keepends=True)
            except UnicodeDecodeError:
                parts.append(f"Binary files a/{path} and b/{path} differ\n")
                continue
            diff_lines = list(
                difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}")
            )
            parts.extend(diff_lines)
            added += sum(
                1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
            )
            deleted += sum(
                1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
            )
        return WorkspaceDiff(
            patch="".join(parts),
            changed_files=changed,
            added_lines=added,
            deleted_lines=deleted,
        )

    def close(self) -> None:
        if not self._closed:
            for temporary in self._read_only_temporaries:
                temporary.cleanup()
            self._temporary.cleanup()
            self._closed = True

    def __enter__(self) -> LocalRuntimeSession:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class LocalRuntime(Runtime):
    _descriptor = RuntimeDescriptor(
        schema_version=SCHEMA_VERSION,
        name="local",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=["trusted_local", "timeouts", "bounded_output"],
        isolation_level="local_trusted",
        deterministic=True,
    )

    @property
    def descriptor(self) -> RuntimeDescriptor:
        return self._descriptor

    def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(
            healthy=True,
            message="available (trusted development runtime; not an untrusted-code sandbox)",
        )

    def create_session(self, spec: SessionSpec) -> LocalRuntimeSession:
        return LocalRuntimeSession(spec)
