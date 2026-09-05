"""Materialize the public-only workspace and compile contract for AgentEval tasks."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.schemas.runtime import SessionReadOnlyMount


@dataclass(frozen=True)
class AgentEvalWorkspace:
    temporary: tempfile.TemporaryDirectory[str]
    visible_root: Path
    read_only_mount: SessionReadOnlyMount | None
    public_test_contract_hash: str | None


def compile_feedback_contract(
    *,
    source_paths: list[str],
    top_module: str,
    language: str,
) -> dict[str, object]:
    """Build one deterministic syntax/elaboration-only Icarus contract."""

    if language not in {"2005", "2012"}:
        raise ValueError("agent compile feedback supports Verilog 2005 or SystemVerilog 2012")
    normalized = [_safe_repository_path(path) for path in source_paths]
    if not normalized:
        raise ValueError("agent compile feedback requires at least one source")
    if not top_module or any(
        not (character.isalnum() or character == "_") for character in top_module
    ):
        raise ValueError("agent compile feedback top module is invalid")
    notice = b"VeriGym AgentEval public compile interface. No hidden testbench is present.\n"
    asset_path = "assets/NOTICE"
    asset_files = {asset_path: hash_bytes(notice)}
    public_assets_hash = _public_asset_hash({asset_path: notice})
    return {
        "schema_version": "1.0",
        "protocol": "verigym_public_test_v1",
        "contract_file": "test-contract.json",
        "mount_destination": "/verigym-public",
        "public_assets_hash": public_assets_hash,
        "asset_files": asset_files,
        "max_feedback_bytes": 65_536,
        "max_build_bytes": 32 * 1024 * 1024,
        "tests": [
            {
                "id": "compile",
                "title": "Public Icarus syntax and elaboration check",
                "commands": [
                    {
                        "argv": [
                            "iverilog",
                            f"-g{language}",
                            "-s",
                            top_module,
                            "-o",
                            "{build}/compile-only",
                            *(f"{{repository}}/{path}" for path in normalized),
                        ],
                        "cwd": "repository",
                        "timeout_s": 30,
                        "expected_exit_code": 0,
                    }
                ],
            }
        ],
    }


def compile_smoke_feedback_contract(
    *,
    source_paths: list[str],
    top_module: str,
    language: str,
    public_testbench: str,
    testbench_top: str = "public_smoke",
) -> dict[str, object]:
    """Build a deterministic compile plus public functional-smoke contract."""

    contract = compile_feedback_contract(
        source_paths=source_paths,
        top_module=top_module,
        language=language,
    )
    if not public_testbench.strip():
        raise ValueError("agent public smoke testbench cannot be empty")
    if not testbench_top or any(
        not (character.isalnum() or character == "_") for character in testbench_top
    ):
        raise ValueError("agent public smoke testbench top module is invalid")
    notice = b"VeriGym AgentEval public compile and functional smoke interface.\n"
    testbench = public_testbench.rstrip().encode("utf-8") + b"\n"
    files = {
        "assets/NOTICE": notice,
        "assets/public-smoke.sv": testbench,
    }
    contract.update(
        {
            "public_assets_hash": _public_asset_hash(files),
            "asset_files": {path: hash_bytes(data) for path, data in sorted(files.items())},
            "tests": [
                {
                    "id": "compile",
                    "title": "Public compile and bounded functional smoke simulation",
                    "commands": [
                        {
                            "argv": [
                                "iverilog",
                                f"-g{language}",
                                "-s",
                                testbench_top,
                                "-o",
                                "{build}/public-smoke",
                                *(f"{{repository}}/{path}" for path in source_paths),
                                "{public}/assets/public-smoke.sv",
                            ],
                            "cwd": "repository",
                            "timeout_s": 30,
                            "expected_exit_code": 0,
                        },
                        {
                            "argv": ["vvp", "{build}/public-smoke"],
                            "cwd": "repository",
                            "timeout_s": 30,
                            "expected_exit_code": 0,
                        },
                    ],
                }
            ],
        }
    )
    return contract


def materialize_agent_eval_workspace(
    *,
    task_description: str,
    repository_files: dict[str, str],
    compile_contract: dict[str, object] | None,
    ppa_available: bool,
    public_asset_files: dict[str, str] | None = None,
) -> AgentEvalWorkspace:
    """Create one retained temporary projection with no verifier-only material."""

    temporary = tempfile.TemporaryDirectory(prefix="verigym-agent-eval-visible-")
    root = Path(temporary.name).resolve()
    visible = root / "visible"
    repository = visible / "repository"
    repository.mkdir(parents=True)
    for raw_path, text in sorted(repository_files.items()):
        relative = _safe_repository_path(raw_path)
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    (visible / "TASK.md").write_text(task_description.rstrip() + "\n", encoding="utf-8")
    public_ids = ["compile"] if compile_contract is not None else []
    lines = ["# AgentEval feedback", ""]
    if public_ids:
        lines.extend(
            [
                "Use `run_public_test` only with an ID listed below.",
                "",
                *(f"- `{test_id}`" for test_id in public_ids),
                "",
                (
                    "`compile` runs the task-declared public validation contract. It contains "
                    "no hidden testbench."
                    if public_asset_files
                    else "`compile` is public syntax/elaboration only and contains no hidden "
                    "testbench."
                ),
            ]
        )
    else:
        lines.append("This task exposes no public test. Inspect the current diff before finish.")
    if ppa_available:
        lines.extend(
            [
                "`ppa` is available only when the run-resolved prompt lists it and after compile "
                "passes.",
                "It returns candidate-only metrics under the frozen resolved profile.",
            ]
        )
    (visible / "PUBLIC_TESTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if compile_contract is None:
        return AgentEvalWorkspace(temporary, visible, None, None)
    public = root / "public"
    files = {
        "assets/NOTICE": (
            "VeriGym AgentEval public compile and functional smoke interface.\n"
            if public_asset_files
            else "VeriGym AgentEval public compile interface. No hidden testbench is present.\n"
        ),
        **(public_asset_files or {}),
    }
    declared = compile_contract.get("asset_files")
    observed = {
        path: hash_bytes(text.rstrip().encode("utf-8") + b"\n")
        for path, text in sorted(files.items())
    }
    if declared != observed:
        raise ValueError("AgentEval public assets differ from the frozen compile contract")
    for raw_path, text in sorted(files.items()):
        relative = _safe_repository_path(raw_path)
        destination = public / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text.rstrip() + "\n", encoding="utf-8")
    (public / "test-contract.json").write_text(
        json.dumps(compile_contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return AgentEvalWorkspace(
        temporary=temporary,
        visible_root=visible,
        read_only_mount=SessionReadOnlyMount(
            source_dir=str(public),
            destination="/verigym-public",
            content_hash=hash_directory(public),
            label="public_tests",
        ),
        public_test_contract_hash=content_hash(compile_contract),
    )


def _safe_repository_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise ValueError("AgentEval repository paths must be canonical and relative")
    return value


def _public_asset_hash(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative, data in sorted(files.items()):
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


__all__ = [
    "AgentEvalWorkspace",
    "compile_feedback_contract",
    "compile_smoke_feedback_contract",
    "materialize_agent_eval_workspace",
]
