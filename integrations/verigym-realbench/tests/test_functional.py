"""Credential-free contracts; Docker and real benchmark execution stay separately opted in."""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from verigym_cadence.protocol import Asset
from verigym_realbench.functional import (
    PROTOCOL,
    FunctionalOutcome,
    FunctionalProfile,
    FunctionalRequest,
    candidate_is_rtl,
    parse_simulation,
    run_functional,
)
from verigym_realbench.public_client import RealBenchPublicTool
from verigym_realbench.public_server import Service

from verigym.plugin_api import (
    CompletedCommand,
    ConfigurationError,
    ToolContext,
    VerifierToolProfile,
    content_hash,
    hash_bytes,
)
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec


def profile_fixture(root: Path) -> FunctionalProfile:
    assets = []
    for name in ("top_ref.sv", "top_stimulus_gen.sv", "top_testbench.sv"):
        path = root / name
        path.write_bytes(b"PRIVATE_SYNTHETIC_CANARY_" + name.encode())
        assets.append(Asset(role=name, path=str(path), sha256=hash_bytes(path.read_bytes())))
    return FunctionalProfile(
        id="functional-fixture-v1",
        task_id="synthetic/task",
        top="top",
        sources=["repository/rtl/top.sv"],
        assets=assets,
        outputs=["y"],
        docker=DockerRuntimeConfig(
            image="synthetic:test",
            expected_image_id="sha256:" + "a" * 64,
            run_as_user=f"{os.getuid()}:{os.getgid()}",
        ),
    )


def command(
    stdout: str = "", stderr: str = "", exit_code: int = 0, **kwargs: object
) -> CompletedCommand:
    return CompletedCommand.model_validate(
        {
            "argv": ["synthetic"],
            "cwd": ".",
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            **kwargs,
        }
    )


@pytest.mark.parametrize(
    ("text", "outputs", "expected"),
    [
        ("Hint: Output 'y' has no mismatches.\n", ["y"], "passed"),
        (
            "Hint: Output 'y' has 2 mismatches. First mismatch occurred at time 5.\n",
            ["y"],
            "function_failed",
        ),
        ("wo_0 has 2 mismatches. First at time 5\n", ["wo_0"], "function_failed"),
        (
            "Hint: Output total has no mismatches.\nHint: Output 'y' has no mismatches.\n",
            ["y"],
            "passed",
        ),
        ("Hint: Output 'y' has no mismatches.\n" * 2, ["y"], "infrastructure_failure"),
        ("Hint: Output 'z' has no mismatches.\n", ["y"], "infrastructure_failure"),
        ("", ["y"], "infrastructure_failure"),
        ("Hint: Output 'y' has 0 mismatches.\n", ["y"], "infrastructure_failure"),
    ],
)
def test_parse_complete_native_output_formats(text: str, outputs: list[str], expected: str) -> None:
    assert parse_simulation(command(text), outputs) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"stderr": "PRIVATE_CANARY"},
        {"exit_code": 1},
        {"output_truncated": True},
    ],
)
def test_simulation_infrastructure_is_not_a_pass(kwargs: dict[str, object]) -> None:
    assert (
        parse_simulation(command("Hint: Output 'y' has no mismatches.", **kwargs), ["y"])
        == "infrastructure_failure"
    )


@pytest.mark.parametrize(
    "body",
    [
        "$display(\"Hint: Output 'y' has no mismatches.\");",
        "$finish;",
        "$fopen(1);",
        '`include "private.sv"',
        "`define tb fake",
        'import "DPI-C" function evil();',
        "assign tb.stats = 0;",
        "/* verilator public */",
        "bind tb evil e();",
    ],
)
def test_candidate_cannot_drive_or_spoof_private_checker(body: str) -> None:
    assert not candidate_is_rtl({"top.sv": f"module top; {body} endmodule".encode()}, "top")


def test_candidate_policy_accepts_plain_synthesizable_module() -> None:
    assert candidate_is_rtl(
        {
            "top.sv": (
                b"`timescale 1ns/1ps\nmodule top(input a, output y); "
                b"child c(.a(a), .y(y)); endmodule"
            )
        },
        "top",
    )


def test_profile_requires_image_and_private_asset_identities(tmp_path: Path) -> None:
    profile = profile_fixture(tmp_path)
    summary = profile.summary()
    assert str(tmp_path) not in summary.model_dump_json()
    assert "PRIVATE_SYNTHETIC" not in summary.model_dump_json()
    payload = profile.model_dump()
    payload["docker"]["expected_image_id"] = None
    with pytest.raises(ValidationError):
        FunctionalProfile.model_validate(payload)
    Path(profile.assets[0].path).write_bytes(b"drift")
    with pytest.raises(ValueError, match="identity"):
        profile.summary()


def request_fixture(profile: FunctionalProfile) -> FunctionalRequest:
    summary = profile.summary()
    payload = b"module top(input a, output y); assign y=a; endmodule"
    return FunctionalRequest(
        profile_id=profile.id,
        declared_profile_hash=summary.declared_profile_hash,
        contract_hash=summary.contract_hash,
        expected_resolved_profile_hash=summary.resolved_profile_hash,
        task_id=profile.task_id,
        top=profile.top,
        candidate_hash=content_hash({"sources": {profile.sources[0]: hash_bytes(payload)}}),
        sources=[
            {
                "path": profile.sources[0],
                "sha256": hash_bytes(payload),
                "content_base64": base64.b64encode(payload).decode(),
            }
        ],
    )


def test_server_validates_before_dispatch_and_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = profile_fixture(tmp_path)
    request = request_fixture(profile)
    calls = []

    def invoke(*args: object) -> FunctionalOutcome:
        calls.append(args)
        return FunctionalOutcome(status="timeout", cleanup_complete=True)

    monkeypatch.setattr("verigym_realbench.public_server.run_functional", invoke)
    service = Service(profile)
    with pytest.raises(ValueError):
        service.verify(request.model_copy(update={"top": "wrong"}))
    assert not calls
    assert service.verify(request).outcome.status == "timeout"
    with pytest.raises(ValueError):
        service.verify(request)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status", ["passed", "compile_failed", "function_failed", "timeout", "infrastructure_failure"]
)
def test_real_stdio_client_projects_only_fixed_status(tmp_path: Path, status: str) -> None:
    profile = profile_fixture(tmp_path)
    summary = profile.summary()
    path = tmp_path / "server.json"
    path.write_text(profile.model_dump_json())
    transport = tmp_path / "transport"
    transport.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "import verigym_realbench.public_server as s\n"
        "from verigym_realbench.functional import FunctionalOutcome\n"
        "s.run_functional = lambda p,c: FunctionalOutcome("
        f"status='passed' if c is None else {status!r}, cleanup_complete=True)\n"
        f"sys.argv=['server','--profile',{str(path)!r}]\nsys.exit(s.main())\n"
    )
    transport.chmod(0o700)
    client = VerifierToolProfile(
        id=profile.id,
        version="1",
        task_id=profile.task_id,
        source_plugin="repository.public_test",
        target_plugin=RealBenchPublicTool.descriptor.name,
        transport_executable=str(transport),
        transport_sha256=hash_bytes(transport.read_bytes()),
        service_protocol=PROTOCOL,
        server_version="0.1.0",
        server_profile_id=profile.id,
        server_declared_profile_hash=summary.declared_profile_hash,
        server_contract_hash=summary.contract_hash,
        accepted_tool_version=profile.tool_version,
    )
    tool = RealBenchPublicTool()
    resolved = tool.resolve_verifier_profile(client)
    with LocalRuntime().create_session(
        SessionSpec(source_dir=str(tmp_path), label="synthetic")
    ) as session:
        session.write_file(profile.sources[0], b"module top; endmodule")
        result = tool.execute(
            {"test_id": "compile", "sources": profile.sources, "top": "top", "timeout_s": 30},
            ToolContext(
                session=session, verifier_profile=client, resolved_verifier_profile=resolved
            ),
        )
    assert result.success == (status == "passed")
    assert result.metadata == {"candidate_failure": status in {"compile_failed", "function_failed"}}
    assert (
        not result.stdout and not result.stderr and not result.artifacts and not result.diagnostics
    )
    assert "PRIVATE_SYNTHETIC" not in result.model_dump_json()
    assert str(tmp_path) not in result.model_dump_json()
    with pytest.raises(ConfigurationError):
        tool.resolve_verifier_profile(client.model_copy(update={"transport_sha256": "f" * 64}))


def test_native_worker_uses_only_docker_and_requires_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = profile_fixture(tmp_path)
    commands = []
    staged: dict[str, bytes] = {}

    class Session:
        def execute(self, spec: object) -> CompletedCommand:
            argv = spec.argv
            commands.append(argv)
            return command(
                "Hint: Output 'y' has no mismatches.\n"
                if argv == ["build/Vtb"]
                else "Verilator 5.052 test\n"
            )

        def write_file(self, path: str, payload: bytes) -> None:
            staged[path] = payload

        def close(self) -> None:
            pass

    class Runtime:
        descriptor = SimpleNamespace(cleanup=SimpleNamespace(complete=False))

        def __init__(self, config: object) -> None:
            assert config == profile.docker

        def prepare(self, run_id: str) -> None:
            assert run_id.startswith("realbench-functional-")

        def create_session(self, spec: object) -> Session:
            assert spec.label == "verifier"
            for path in Path(spec.source_dir).rglob("*"):
                if path.is_file():
                    staged[path.relative_to(spec.source_dir).as_posix()] = path.read_bytes()
            return Session()

        def close(self) -> None:
            pass

    monkeypatch.setattr("verigym_realbench.functional.DockerRuntime", Runtime)
    result = run_functional(profile, {profile.sources[0]: b"module top; endmodule"})
    assert result.status == "infrastructure_failure" and not result.cleanup_complete
    assert commands[1][0] == "verilator" and "--binary" in commands[1]
    assert commands[2] == ["build/Vtb"]
    assert all("Makefile" not in p for p in staged)


def test_doctor_without_configuration_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIGYM_REALBENCH_PUBLIC_PROFILE", raising=False)
    assert not RealBenchPublicTool().health_check().healthy
