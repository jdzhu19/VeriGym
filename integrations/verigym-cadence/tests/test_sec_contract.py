"""Credential-free real stdio tests; no commercial binaries or proprietary inputs."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from verigym_cadence.client import JasperGoldMcpTool, rpc
from verigym_cadence.native_worker import parse_sec, read_sec_log, run
from verigym_cadence.protocol import (
    PROTOCOL,
    VERSION,
    Asset,
    ServerProfile,
    Source,
    VerifyRequest,
    bounded_read,
    unique_json,
)
from verigym_cadence.server import Service, worker_call

from verigym.plugin_api import (
    CompletedCommand,
    ConfigurationError,
    ToolContext,
    VerifierToolProfile,
    content_hash,
    hash_bytes,
)
from verigym.runtimes.local import LocalRuntime, LocalRuntimeSession
from verigym.schemas.runtime import SessionSpec


def executable(path: Path, code: str) -> Asset:
    path.write_text(f"#!{sys.executable}\n{code}", encoding="utf-8")
    path.chmod(0o700)
    return Asset(role="worker", path=str(path), sha256=hash_bytes(path.read_bytes()))


def fixture(tmp_path: Path, outcome: dict[str, Any]) -> tuple[ServerProfile, VerifierToolProfile]:
    worker = executable(
        tmp_path / "worker.py",
        (
            "import json, sys\n"
            "p = json.load(sys.stdin)\n"
            "print(json.dumps({'tool_version': '2022.12', 'yosys_version': '0.55'} "
            f"if p['operation'] == 'probe' else {outcome!r}))\n"
        ),
    )
    asset = tmp_path / "private.txt"
    asset.write_text("PRIVATE_GOLDEN_CANARY", encoding="utf-8")
    profile = ServerProfile(
        id="fixture",
        version="1",
        task_id="realbench/fixture",
        top="top",
        sources=["repository/top.sv"],
        tool_version="2022.12",
        yosys_version="0.55",
        worker=worker,
        assets=[Asset(role="reference", path=str(asset), sha256=hash_bytes(asset.read_bytes()))],
        approved_candidate_hashes=[
            content_hash({"sources": {"repository/top.sv": hash_bytes(b"module top; endmodule\n")}})
        ],
        timeout_s=5,
    )
    private_profile = tmp_path / "profile.json"
    private_profile.write_text(profile.model_dump_json(), encoding="utf-8")
    wrapper = executable(
        tmp_path / "transport.py",
        (
            "import sys\nfrom verigym_cadence.server import main\n"
            f"sys.argv = ['server', '--profile', {str(private_profile)!r}]\n"
            "raise SystemExit(main())\n"
        ),
    )
    summary = profile.resolve()
    client = VerifierToolProfile(
        id="client",
        version="1",
        task_id=profile.task_id,
        source_plugin="realbench.sec",
        target_plugin=JasperGoldMcpTool.descriptor.name,
        transport_executable=wrapper.path,
        transport_sha256=wrapper.sha256,
        service_protocol=PROTOCOL,
        server_version=VERSION,
        server_profile_id=profile.id,
        server_declared_profile_hash=summary.declared_profile_hash,
        server_contract_hash=summary.contract_hash,
        accepted_tool_version=profile.tool_version,
    )
    return profile, client


@pytest.mark.parametrize(
    "status,candidate_failure",
    [
        ("proven", False),
        ("counterexample", True),
        ("candidate_compile_failure", True),
        ("inconclusive", False),
        ("timeout", False),
        ("license_unavailable", False),
        ("tool_unavailable", False),
        ("infrastructure_failure", False),
    ],
)
def test_actual_stdio_preserves_outcome_and_hides_assets(
    tmp_path: Path,
    status: str,
    candidate_failure: bool,
) -> None:
    _, profile = fixture(tmp_path, {"status": status})
    tool = JasperGoldMcpTool()
    resolved = tool.resolve_verifier_profile(profile)
    assert tool.resolve_verifier_profile(profile, expected=resolved) == resolved
    source = tmp_path / "candidate"
    (source / "repository").mkdir(parents=True)
    (source / "repository/top.sv").write_bytes(b"module top; endmodule\n")
    with LocalRuntime().create_session(SessionSpec(source_dir=str(source), label="candidate")) as s:
        result = tool.execute(
            {"sources": ["repository/top.sv"], "top": "top", "timeout_s": 5},
            ToolContext(session=s, verifier_profile=profile, resolved_verifier_profile=resolved),
        )
    assert result.success is (status == "proven")
    assert result.message == status
    assert result.metadata["candidate_failure"] is candidate_failure
    assert (
        not result.stdout and not result.stderr and not result.artifacts and not result.diagnostics
    )
    assert "PRIVATE_GOLDEN_CANARY" not in result.model_dump_json()
    assert str(tmp_path) not in result.model_dump_json()


def test_extra_hidden_response_fields_fail_closed(tmp_path: Path) -> None:
    _, profile = fixture(tmp_path, {"status": "proven", "raw_cex": "PRIVATE_GOLDEN_CANARY"})
    tool = JasperGoldMcpTool()
    resolved = tool.resolve_verifier_profile(profile)
    source = tmp_path / "candidate"
    (source / "repository").mkdir(parents=True)
    (source / "repository/top.sv").write_bytes(b"module top; endmodule\n")
    with LocalRuntime().create_session(SessionSpec(source_dir=str(source), label="candidate")) as s:
        result = tool.execute(
            {"sources": ["repository/top.sv"], "top": "top"},
            ToolContext(session=s, verifier_profile=profile, resolved_verifier_profile=resolved),
        )
    assert result.message == "infrastructure_failure"
    assert "PRIVATE_GOLDEN_CANARY" not in result.model_dump_json()


def request_for(profile: ServerProfile, data: bytes = b"module top; endmodule\n") -> VerifyRequest:
    summary = profile.resolve()
    source = Source(
        path=profile.sources[0],
        sha256=hash_bytes(data),
        content_base64=base64.b64encode(data).decode("ascii"),
    )
    return VerifyRequest(
        top=profile.top,
        profile_id=profile.id,
        declared_profile_hash=summary.declared_profile_hash,
        contract_hash=summary.contract_hash,
        expected_resolved_profile_hash=summary.resolved_profile_hash,
        task_id=profile.task_id,
        sources=[source],
        candidate_hash=content_hash({"sources": {source.path: source.sha256}}),
    )


def test_unknown_candidate_rejected_before_worker_and_no_retry(tmp_path: Path) -> None:
    profile, _ = fixture(tmp_path, {"status": "proven"})
    service = Service(profile)
    with pytest.raises(ValueError, match="outside"):
        service.verify(request_for(profile, b"untrusted model code"))
    assert not service.verified
    assert service.verify(request_for(profile)).outcome.status == "proven"
    with pytest.raises(ValueError, match="one SEC"):
        service.verify(request_for(profile))


def test_profile_asset_and_transport_drift_rejected(tmp_path: Path) -> None:
    profile, client = fixture(tmp_path, {"status": "proven"})
    tool = JasperGoldMcpTool()
    resolved = tool.resolve_verifier_profile(client)
    with pytest.raises(ConfigurationError):
        tool.resolve_verifier_profile(
            client.model_copy(update={"accepted_tool_version": "2099.01"})
        )
    Path(profile.assets[0].path).write_text("changed", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        tool.resolve_verifier_profile(client, expected=resolved)
    Path(client.transport_executable).write_text("changed", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="transport identity"):
        rpc(client, "resolve_profile", {}, 1)


@pytest.mark.parametrize(
    "path",
    ["../x.sv", "/x.sv", "a/./x.sv", "a//x.sv", ".hidden/x.sv", "x.sv;exit", "x.tcl", "x\\y.sv"],
)
def test_candidate_paths_reject_escape_and_code_injection(path: str) -> None:
    with pytest.raises(ValidationError):
        Source(path=path, sha256="0" * 64, content_base64="")


def test_content_and_symlink_bounds(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Source(path="x.sv", sha256="0" * 64, content_base64="eA==").decode()
    target = tmp_path / "file"
    target.write_bytes(b"abcd")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        bounded_read(link)
    with pytest.raises(ValueError, match="bounded"):
        bounded_read(target, 3)
    with pytest.raises(ValueError, match="duplicate"):
        unique_json('{"status":"proven","status":"counterexample"}')


@pytest.mark.parametrize(
    "log,exit_code,status",
    [
        ("JPW: proven\n", 0, "proven"),
        ("JPW: cex\n", 0, "counterexample"),
        ("JPW: determined_or_skipped\n", 0, "inconclusive"),
        ("", 0, "infrastructure_failure"),
        ("JPW: proven\nJPW: cex\n", 0, "infrastructure_failure"),
        ("JPW: proven\n", 1, "infrastructure_failure"),
        ("license checkout failed\n", 1, "license_unavailable"),
    ],
)
def test_sec_native_parser_does_not_equate_no_cex_with_proof(
    log: str,
    exit_code: int,
    status: str,
) -> None:
    completed = CompletedCommand(argv=["jg"], cwd=".", exit_code=exit_code)
    assert parse_sec(completed, log).status == status


def test_doctor_without_profile_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIGYM_JASPERGOLD_MCP_PROFILE", raising=False)
    assert not JasperGoldMcpTool().health_check().healthy


@pytest.mark.parametrize("operation", ["probe", "verify"])
@pytest.mark.parametrize("configured", [False, True])
def test_worker_receives_only_site_license_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    configured: bool,
) -> None:
    profile, _ = fixture(tmp_path, {"status": "proven"})
    expected = {"CDS_LIC_FILE": "synthetic-cds", "LM_LICENSE_FILE": "synthetic-lm"}
    for name, value in expected.items():
        if configured:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERIGYM_UNRELATED_SECRET", "synthetic-unrelated")
    worker = executable(
        tmp_path / "license-worker.py",
        "import json, os, sys\n"
        "raw = sys.stdin.read()\n"
        "payload = json.loads(raw)\n"
        f"expected = {expected if configured else {}!r}\n"
        "actual = {n: os.environ[n] for n in ('CDS_LIC_FILE', 'LM_LICENSE_FILE') "
        "if n in os.environ}\n"
        "assert actual == expected\n"
        "assert 'VERIGYM_UNRELATED_SECRET' not in os.environ\n"
        "assert all(value not in raw for value in expected.values())\n"
        "print(json.dumps({'tool_version': '2022.12', 'yosys_version': '0.55'} "
        "if payload['operation'] == 'probe' else {'status': 'proven'}))\n",
    )
    profile = profile.model_copy(update={"worker": worker})
    result = worker_call(
        profile, operation, request_for(profile) if operation == "verify" else None
    )
    assert result == (
        {"tool_version": "2022.12", "yosys_version": "0.55"}
        if operation == "probe"
        else {"status": "proven"}
    )
    assert not any(value in str(result) for value in expected.values())


@pytest.mark.parametrize("status", ["proven", "cex"])
@pytest.mark.parametrize("version", ["2022.12", "2022.12p001"])
@pytest.mark.parametrize("linked_log", [False, True])
def test_native_worker_runs_fixed_yosys_sec_flow_and_cleans_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    version: str,
    linked_log: bool,
) -> None:
    profile, _ = fixture(tmp_path, {"status": "proven"})
    yosys = executable(
        tmp_path / "yosys.py",
        (
            "import sys\nfrom pathlib import Path\n"
            "if sys.argv[1:] == ['-V']: print('Yosys 0.55')\n"
            "else:\n"
            " assert sys.argv[1] == '-p'\n"
            " assert 'read_verilog -sv' in sys.argv[2]\n"
            " Path(sys.argv[2].split('write_verilog ')[1]).write_text('module top; endmodule')\n"
        ),
    ).model_copy(update={"role": "yosys"})
    jg = executable(
        tmp_path / "jg.py",
        (
            "import sys\nfrom pathlib import Path\n"
            f"if sys.argv[1:] == ['-version']: print('JasperGold {version}')\n"
            "else:\n"
            " assert sys.argv[1:] == ['-no_gui', '-sec', 'test.tcl']\n"
            " assert Path('a.v').is_file() and Path('b.v').is_file()\n"
            " assert '###TOPMODULE###' not in Path('test.tcl').read_text()\n"
            " Path('jgproject').mkdir()\n"
            " log = Path('jgproject/jg.log')\n"
            f" if {linked_log!r}:\n"
            "  log = Path('jgproject/sessionLogs/session_0/jg.log')\n"
            "  log.parent.mkdir(parents=True)\n"
            "  Path('jgproject/jg.log').symlink_to('sessionLogs/session_0/jg.log')\n"
            f" log.write_text('PRIVATE_CEX_CANARY\\nJPW: {status}\\n')\n"
        ),
    ).model_copy(update={"role": "jaspergold"})
    ref = tmp_path / "ref.sv"
    ref.write_text("module ref_top; endmodule\n", encoding="utf-8")
    template = tmp_path / "sec.tcl"
    template.write_text("# synthetic template ###TOPMODULE###\n", encoding="utf-8")
    profile = profile.model_copy(
        update={
            "tool_version": version,
            "assets": [
                jg,
                yosys,
                Asset(role="reference:ref.sv", path=str(ref), sha256=hash_bytes(ref.read_bytes())),
                Asset(
                    role="sec_template",
                    path=str(template),
                    sha256=hash_bytes(template.read_bytes()),
                ),
            ],
        }
    )
    request = request_for(profile)
    # Restrict temporary directories to this test's owned scratch, then check cleanup.
    import tempfile

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    result = run(
        {"operation": "verify", "profile": profile.model_dump(), "request": request.model_dump()}
    )
    assert result == {"status": "proven" if status == "proven" else "counterexample"}
    assert list(scratch.iterdir()) == []


def test_native_worker_has_one_deadline_across_all_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    import verigym_cadence.native_worker as native

    profile, _ = fixture(tmp_path, {"status": "proven"})
    reference = tmp_path / "reference.sv"
    reference.write_text("module ref_top; endmodule\n", encoding="ascii")
    template = tmp_path / "sec.tcl"
    template.write_text("# ###TOPMODULE###\n", encoding="ascii")
    profile = profile.model_copy(
        update={
            "timeout_s": 2,
            "assets": [
                profile.worker.model_copy(update={"role": "jaspergold"}),
                profile.worker.model_copy(update={"role": "yosys"}),
                Asset(
                    role="reference:ref.sv",
                    path=str(reference),
                    sha256=hash_bytes(reference.read_bytes()),
                ),
                Asset(
                    role="sec_template",
                    path=str(template),
                    sha256=hash_bytes(template.read_bytes()),
                ),
            ],
        }
    )
    request = request_for(profile)
    phases: list[str] = []

    def fake_execute(
        session: LocalRuntimeSession, argv: list[str], timeout: int
    ) -> CompletedCommand:
        if argv[1:] == ["-version"]:
            return CompletedCommand(argv=argv, cwd=".", exit_code=0, stdout="JasperGold 2022.12")
        if argv[1:] == ["-V"]:
            return CompletedCommand(argv=argv, cwd=".", exit_code=0, stdout="Yosys 0.55")
        phase = "synthesis" if argv[1] == "-p" else "sec"
        phases.append(phase)
        delay = min(1.1, timeout)
        time.sleep(delay)
        if phase == "sec":
            (session.root / "jgproject").mkdir()
            (session.root / "jgproject/jg.log").write_text("JPW: proven\n", encoding="ascii")
        return CompletedCommand(argv=argv, cwd=".", exit_code=0, timed_out=delay < 1.1)

    monkeypatch.setattr(native, "_execute", fake_execute)
    started = time.monotonic()
    result = native.run(
        {"operation": "verify", "profile": profile.model_dump(), "request": request.model_dump()}
    )
    assert result == {"status": "timeout"}
    assert phases == ["synthesis", "synthesis"]  # Do not spend a third budget on SEC.
    assert time.monotonic() - started < 3.2  # Integer command limits can overshoot by < 1 s.


@pytest.mark.parametrize("elapsed", [0.0, 1.5, 2.0])
def test_expired_native_deadline_never_launches_or_accepts_late_proof(
    monkeypatch: pytest.MonkeyPatch, elapsed: float
) -> None:
    import verigym_cadence.native_worker as native

    clock = [elapsed]
    calls: list[int] = []
    monkeypatch.setattr(native.time, "monotonic", lambda: clock[0])

    def execute(session: Any, argv: list[str], timeout: int) -> CompletedCommand:
        calls.append(timeout)
        clock[0] = 2.1
        return CompletedCommand(argv=argv, cwd=".", exit_code=0, stdout="JPW: proven")

    monkeypatch.setattr(native, "_execute", execute)
    result = native._execute_until(None, ["synthetic"], 20, 2.0)
    assert result.timed_out
    assert calls == ([] if elapsed == 2.0 else [2 if elapsed == 0.0 else 1])
    assert native.parse_sec(result, "JPW: proven\n").status == "timeout"


@pytest.mark.parametrize("operation", ["probe", "verify"])
def test_version_timeout_stops_before_second_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    import verigym_cadence.native_worker as native

    profile, _ = fixture(tmp_path, {"status": "proven"})
    profile = profile.model_copy(
        update={
            "assets": [
                profile.worker.model_copy(update={"role": role}) for role in ("jaspergold", "yosys")
            ]
        }
    )
    calls: list[list[str]] = []

    def execute(session: Any, argv: list[str], timeout: int) -> CompletedCommand:
        calls.append(argv)
        return CompletedCommand(argv=argv, cwd=".", exit_code=None, timed_out=True)

    monkeypatch.setattr(native, "_execute", execute)
    result = native.run(
        {
            "operation": operation,
            "profile": profile.model_dump(),
            "request": request_for(profile).model_dump() if operation == "verify" else None,
        }
    )
    assert result == {"status": "tool_unavailable" if operation == "probe" else "timeout"}
    assert len(calls) == 1 and calls[0][1:] == ["-version"]


@pytest.mark.parametrize(
    "layout",
    ["escape", "dangling", "cycle", "project_link", "hardlink", "directory", "fifo", "oversize"],
)
def test_sec_log_rejects_unsafe_or_unbounded_outputs(tmp_path: Path, layout: str) -> None:
    import os

    project = tmp_path / "jgproject"
    project.mkdir()
    log = project / "jg.log"
    outside = tmp_path / "outside.log"
    outside.write_text("JPW: proven\n", encoding="ascii")
    if layout == "escape":
        log.symlink_to(outside)
    elif layout == "dangling":
        log.symlink_to("absent")
    elif layout == "cycle":
        log.symlink_to("jg.log")
    elif layout == "project_link":
        project.rmdir()
        project.symlink_to(tmp_path, target_is_directory=True)
        (tmp_path / "jg.log").write_text("JPW: proven\n", encoding="ascii")
    elif layout == "hardlink":
        os.link(outside, log)
    elif layout == "directory":
        log.mkdir()
    elif layout == "fifo":
        os.mkfifo(log)
    else:
        log.write_bytes(b"x" * 17)
    with pytest.raises(ValueError, match="SEC log"):
        read_sec_log(tmp_path, limit=16)


def test_sec_log_missing_does_not_hide_process_failure(tmp_path: Path) -> None:
    log = read_sec_log(tmp_path)
    assert log == ""
    completed = CompletedCommand(
        argv=["jg"], cwd=".", exit_code=1, stderr="License checkout failed"
    )
    assert parse_sec(completed, log).status == "license_unavailable"


def test_top_and_duplicate_sources_rejected_before_dispatch(tmp_path: Path) -> None:
    profile, _ = fixture(tmp_path, {"status": "proven"})
    request = request_for(profile)
    with pytest.raises(ValueError, match="outside"):
        Service(profile).verify(request.model_copy(update={"top": "other"}))
    with pytest.raises(ValueError, match="duplicate"):
        request.model_copy(update={"sources": request.sources * 2}).candidate()
