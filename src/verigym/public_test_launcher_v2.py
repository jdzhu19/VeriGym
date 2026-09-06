#!/usr/bin/env python3
"""Credential-free trusted launcher for hash-bound repository public tests.

The module deliberately uses only the Python standard library so the exact
source file can also be copied into the separately identified agent image.
"""

from __future__ import annotations

import hashlib
import json
import os
import select
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any

PUBLIC_ROOT = Path("/verigym-public")
WORKSPACE_ROOT = Path("/workspace")
_MAX_CONTRACT_BYTES = 1024 * 1024
_ALLOWED_EXECUTABLES = {"iverilog", "verilator", "vvp"}
TOOLCHAIN_PATH = "/opt/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin"
_TOP_LEVEL_KEYS = {
    "schema_version",
    "protocol",
    "contract_file",
    "mount_destination",
    "public_assets_hash",
    "asset_files",
    "max_feedback_bytes",
    "max_build_bytes",
    "tests",
}
_TEST_KEYS = {"id", "title", "commands"}
_COMMAND_KEYS = {"argv", "cwd", "timeout_s", "expected_exit_code"}


class PublicTestError(Exception):
    """Fail-closed launcher error safe to expose to the task agent."""


def run_cli(
    arguments: list[str],
    *,
    public_root: Path = PUBLIC_ROOT,
    workspace_root: Path = WORKSPACE_ROOT,
) -> int:
    """Execute the exact two-command public interface."""

    try:
        if arguments == ["list"]:
            exit_code, payload, limit = execute_public_test(
                None,
                public_root=public_root,
                workspace_root=workspace_root,
            )
            _emit(payload, limit=limit)
            return exit_code
        if len(arguments) == 2 and arguments[0] == "run":
            exit_code, payload, limit = execute_public_test(
                arguments[1],
                public_root=public_root,
                workspace_root=workspace_root,
            )
            _emit(payload, limit=limit)
            return exit_code
        raise PublicTestError("usage: verigym-public-test list | run <test-id>")
    except PublicTestError as exc:
        _emit(
            {
                "schema_version": "1.0",
                "protocol": "verigym_public_test_v1",
                "passed": False,
                "category": "launcher_error",
                "message": str(exc),
            },
            limit=64 * 1024,
        )
        return 2


def execute_public_test(
    test_id: str | None,
    *,
    public_root: Path,
    workspace_root: Path,
) -> tuple[int, dict[str, Any], int]:
    """Return one trusted launcher result without depending on process globals."""

    started = time.monotonic()
    contract = _load_contract(public_root)
    limit = int(contract["max_feedback_bytes"])
    if test_id is None:
        payload = {
            "schema_version": "1.0",
            "protocol": "verigym_public_test_v1",
            "tests": [{"id": test["id"], "title": test["title"]} for test in contract["tests"]],
        }
        return 0, payload, limit
    result = _run_test(
        contract,
        test_id=test_id,
        public_root=public_root,
        workspace_root=workspace_root,
        started=started,
    )
    return (0 if result["passed"] else 1), result, limit


def _load_contract(public_root: Path) -> dict[str, Any]:
    root = public_root.resolve(strict=True)
    contract_path = root / "test-contract.json"
    _assert_regular_file(contract_path, root)
    data = contract_path.read_bytes()
    if len(data) > _MAX_CONTRACT_BYTES:
        raise PublicTestError("public-test contract exceeds its size limit")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicTestError("public-test contract is not canonical JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_KEYS:
        raise PublicTestError("public-test contract has an unexpected top-level schema")
    if (
        payload["schema_version"] != "1.0"
        or payload["protocol"] != "verigym_public_test_v1"
        or payload["contract_file"] != "test-contract.json"
        or payload["mount_destination"] != "/verigym-public"
    ):
        raise PublicTestError("public-test protocol identity is invalid")
    max_feedback = payload["max_feedback_bytes"]
    max_build = payload["max_build_bytes"]
    if (
        not isinstance(max_feedback, int)
        or isinstance(max_feedback, bool)
        or not 1024 <= max_feedback <= 1024 * 1024
        or not isinstance(max_build, int)
        or isinstance(max_build, bool)
        or not 1024 <= max_build <= 512 * 1024 * 1024
    ):
        raise PublicTestError("public-test resource bounds are invalid")
    asset_files = payload["asset_files"]
    if not isinstance(asset_files, dict) or not asset_files or len(asset_files) > 256:
        raise PublicTestError("public-test asset identity is invalid")
    observed: dict[str, str] = {}
    for relative, expected in sorted(asset_files.items()):
        normalized = _relative_asset_path(relative)
        if not isinstance(expected, str) or not _is_sha256(expected):
            raise PublicTestError("public-test asset hash is invalid")
        path = root / normalized
        _assert_regular_file(path, root)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise PublicTestError(f"public-test asset identity changed: {normalized}")
        observed[normalized] = digest
    if _hash_asset_files(root, observed) != payload["public_assets_hash"]:
        raise PublicTestError("public-test aggregate asset identity changed")
    tests = payload["tests"]
    if not isinstance(tests, list) or not tests or len(tests) > 64:
        raise PublicTestError("public-test list is invalid")
    identifiers: set[str] = set()
    for test in tests:
        _validate_test(test, identifiers)
    return payload


def _validate_test(test: object, identifiers: set[str]) -> None:
    if not isinstance(test, dict) or set(test) != _TEST_KEYS:
        raise PublicTestError("public-test entry has an unexpected schema")
    identifier = test["id"]
    if (
        not isinstance(identifier, str)
        or not identifier
        or len(identifier) > 128
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in identifier
        )
        or identifier in identifiers
    ):
        raise PublicTestError("public-test ID is invalid or duplicated")
    identifiers.add(identifier)
    if not isinstance(test["title"], str) or not test["title"] or len(test["title"]) > 512:
        raise PublicTestError("public-test title is invalid")
    commands = test["commands"]
    if not isinstance(commands, list) or not commands or len(commands) > 16:
        raise PublicTestError("public-test command list is invalid")
    for command in commands:
        if not isinstance(command, dict) or set(command) != _COMMAND_KEYS:
            raise PublicTestError("public-test command has an unexpected schema")
        argv = command["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 64
            or any(
                not isinstance(value, str)
                or not value
                or len(value) > 4096
                or any(character in value for character in ("\x00", "\r", "\n"))
                for value in argv
            )
        ):
            raise PublicTestError("public-test argv is invalid")
        if argv[0] not in _ALLOWED_EXECUTABLES:
            raise PublicTestError("public-test executable is outside the strict allowlist")
        if command["cwd"] not in {"repository", "build"}:
            raise PublicTestError("public-test cwd is invalid")
        timeout = command["timeout_s"]
        expected_exit = command["expected_exit_code"]
        if (
            not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or not 1 <= timeout <= 300
            or not isinstance(expected_exit, int)
            or isinstance(expected_exit, bool)
            or not 0 <= expected_exit <= 255
        ):
            raise PublicTestError("public-test command limits are invalid")


def _run_test(
    contract: dict[str, Any],
    *,
    test_id: str,
    public_root: Path,
    workspace_root: Path,
    started: float,
) -> dict[str, Any]:
    matches = [test for test in contract["tests"] if test["id"] == test_id]
    if len(matches) != 1:
        raise PublicTestError("unknown public-test ID")
    repository = (workspace_root / "repository").resolve(strict=True)
    workspace = workspace_root.resolve(strict=True)
    if not repository.is_dir() or not repository.is_relative_to(workspace):
        raise PublicTestError("visible repository workspace is unavailable")
    records: list[dict[str, Any]] = []
    passed = True
    build = Path(f"/tmp/verigym-public-test-{os.getpid()}-{time.monotonic_ns()}")
    try:
        build.mkdir(mode=0o700)
        for sequence, command in enumerate(matches[0]["commands"]):
            argv = [
                _expand_argument(
                    value,
                    repository=repository,
                    public_root=public_root.resolve(strict=True),
                    build=build,
                )
                for value in command["argv"]
            ]
            cwd = repository if command["cwd"] == "repository" else build
            record = _execute(
                argv,
                cwd=cwd,
                timeout_s=command["timeout_s"],
                output_limit=int(contract["max_feedback_bytes"]),
                expected_exit=command["expected_exit_code"],
                sequence=sequence,
            )
            records.append(record)
            if not record["passed"]:
                passed = False
                break
            if _tree_size(build) > int(contract["max_build_bytes"]):
                records.append(
                    {
                        "sequence": sequence,
                        "passed": False,
                        "category": "build_limit",
                        "message": "ephemeral public-test build directory exceeded its byte limit",
                    }
                )
                passed = False
                break
    finally:
        _remove_ephemeral_tree(build)
    return {
        "schema_version": "1.0",
        "protocol": "verigym_public_test_v1",
        "test_id": test_id,
        "passed": passed,
        "category": "passed" if passed else records[-1]["category"],
        "duration_s": round(time.monotonic() - started, 6),
        "commands": records,
        "ephemeral_build_removed": True,
        "network_policy": "runtime_none",
    }


def _execute(
    argv: list[str],
    *,
    cwd: Path,
    timeout_s: int,
    output_limit: int,
    expected_exit: int,
    sequence: int,
) -> dict[str, Any]:
    started = time.monotonic()
    timed_out = False
    stdout = bytearray()
    stderr = bytearray()
    exit_code: int | None = None
    output_exceeded = False
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env={
                "PATH": TOOLCHAIN_PATH,
                "HOME": str(cwd),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
            close_fds=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        os.set_blocking(process.stdout.fileno(), False)
        os.set_blocking(process.stderr.fileno(), False)
        streams = {
            process.stdout.fileno(): stdout,
            process.stderr.fileno(): stderr,
        }
        deadline = started + timeout_s
        while streams:
            now = time.monotonic()
            if now >= deadline:
                timed_out = True
                _kill_process_group(process)
            readable, _, _ = select.select(
                list(streams),
                [],
                [],
                0 if timed_out else min(0.05, max(0.0, deadline - now)),
            )
            for descriptor in readable:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    streams.pop(descriptor, None)
                    continue
                destination = streams[descriptor]
                destination.extend(chunk[: max(0, output_limit + 1 - len(destination))])
                if len(destination) > output_limit:
                    output_exceeded = True
                    _kill_process_group(process)
            if process.poll() is not None and not readable:
                for descriptor in list(streams):
                    chunk = os.read(descriptor, 65536)
                    if chunk:
                        destination = streams[descriptor]
                        destination.extend(chunk[: max(0, output_limit + 1 - len(destination))])
                        if len(destination) > output_limit:
                            output_exceeded = True
                    else:
                        streams.pop(descriptor, None)
        process.wait()
        exit_code = process.returncode
    except (FileNotFoundError, OSError) as exc:
        stderr.extend(str(exc).encode("utf-8")[: output_limit + 1])
        if process is not None:
            _kill_process_group(process)
            process.wait()
    truncated = output_exceeded or len(stdout) > output_limit or len(stderr) > output_limit
    passed = not timed_out and not truncated and exit_code == expected_exit
    category = (
        "passed"
        if passed
        else "timeout"
        if timed_out
        else "output_limit"
        if truncated
        else "command_failed"
    )
    return {
        "sequence": sequence,
        "executable": PurePosixPath(argv[0]).name,
        "argv_hash": hashlib.sha256(
            json.dumps(argv, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "exit_code": exit_code,
        "expected_exit_code": expected_exit,
        "passed": passed,
        "category": category,
        "timed_out": timed_out,
        "output_truncated": truncated,
        "stdout": bytes(stdout[:output_limit]).decode("utf-8", errors="replace"),
        "stderr": bytes(stderr[:output_limit]).decode("utf-8", errors="replace"),
        "stdout_sha256": hashlib.sha256(bytes(stdout[:output_limit])).hexdigest(),
        "stderr_sha256": hashlib.sha256(bytes(stderr[:output_limit])).hexdigest(),
        "duration_s": round(time.monotonic() - started, 6),
    }


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _remove_ephemeral_tree(root: Path) -> None:
    """Remove only the launcher-owned bounded tree without shutil."""

    if not root.name.startswith("verigym-public-test-") or root.parent != Path("/tmp"):
        raise PublicTestError("refusing to clean an unexpected public-test path")
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            raise PublicTestError("ephemeral public-test build contains a symlink")
        if stat.S_ISDIR(metadata.st_mode):
            path.rmdir()
        elif stat.S_ISREG(metadata.st_mode):
            path.unlink()
        else:
            raise PublicTestError("ephemeral public-test build contains an unsafe object")
    root.rmdir()


def _expand_argument(
    value: str,
    *,
    repository: Path,
    public_root: Path,
    build: Path,
) -> str:
    prefixes = {
        "{repository}": repository,
        "{public}": public_root,
        "{build}": build,
    }
    for marker, root in prefixes.items():
        if value == marker:
            return str(root)
        if value.startswith(f"{marker}/"):
            suffix = value[len(marker) + 1 :]
            relative = _safe_relative(suffix)
            target = (root / relative).resolve(strict=False)
            if not target.is_relative_to(root):
                raise PublicTestError("public-test argv path escapes its declared root")
            return str(target)
    if "{" in value or "}" in value:
        raise PublicTestError("public-test argv contains an unknown placeholder")
    if value.startswith("/"):
        raise PublicTestError("public-test argv contains an undeclared absolute path")
    return value


def _relative_asset_path(value: object) -> str:
    if not isinstance(value, str):
        raise PublicTestError("public-test asset path is invalid")
    relative = _safe_relative(value)
    if not relative.startswith("assets/"):
        raise PublicTestError("public-test assets must remain below assets/")
    return relative


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise PublicTestError("public-test path is not canonical and relative")
    return value


def _assert_regular_file(path: Path, root: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
        metadata = os.lstat(path)
    except OSError as exc:
        raise PublicTestError("public-test asset is missing") from exc
    if (
        not resolved.is_relative_to(root)
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise PublicTestError("public-test asset is not a safe regular file")


def _hash_asset_files(root: Path, files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        encoded = relative.encode("utf-8")
        data = (root / relative).read_bytes()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _tree_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode) or not (
            stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
        ):
            raise PublicTestError("ephemeral public-test build contains an unsafe object")
        if stat.S_ISREG(metadata.st_mode):
            total += metadata.st_size
    return total


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _emit(payload: dict[str, Any], *, limit: int) -> None:
    encoded = (json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    if len(encoded) > limit:
        encoded = (
            json.dumps(
                {
                    "schema_version": "1.0",
                    "protocol": "verigym_public_test_v1",
                    "passed": False,
                    "category": "feedback_limit",
                    "message": "public-test feedback exceeded its byte limit",
                },
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    sys.stdout.buffer.write(encoded)


def main() -> None:
    raise SystemExit(run_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
