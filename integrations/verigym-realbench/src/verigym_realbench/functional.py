"""Fixed Docker-only Verilator functional flow; upstream scripts are never executed."""

from __future__ import annotations

import os
import re
import tempfile
import uuid
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from verigym_cadence.protocol import (
    Asset,
    Digest,
    Source,
    VerifyRequest,
    bounded_read,
    relative_path,
)

from verigym.plugin_api import CommandSpec, CompletedCommand, StrictModel, content_hash, hash_bytes
from verigym.runtimes.docker import DockerRuntime
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec

PROTOCOL: Literal["verigym.realbench.verilator.public.mcp.v1"] = (
    "verigym.realbench.verilator.public.mcp.v1"
)
SERVER_NAME = "verigym-realbench-functional"
VERSION: Literal["0.1.0"] = "0.1.0"
Status = Literal["passed", "compile_failed", "function_failed", "timeout", "infrastructure_failure"]
_WARNINGS = (
    "CASEOVERLAP",
    "LATCH",
    "UNOPTFLAT",
    "MULTIDRIVEN",
    "ASCRANGE",
    "IMPLICIT",
    "CASEINCOMPLETE",
    "PINMISSING",
    "WIDTHTRUNC",
    "EOFNEWLINE",
    "DECLFILENAME",
    "WIDTHEXPAND",
)


class FunctionalRequest(VerifyRequest):
    test_id: Literal["compile"] = "compile"


class FunctionalOutcome(StrictModel):
    status: Status
    cleanup_complete: bool
    phase: Literal["policy", "prepare", "probe", "compile", "simulate", "cleanup"] = "policy"
    exit_code: int | None = None


class FunctionalSummary(StrictModel):
    protocol: Literal["verigym.realbench.verilator.public.mcp.v1"] = PROTOCOL
    server_version: Literal["0.1.0"] = VERSION
    profile_id: str
    task_id: str
    top: str
    sources: list[str]
    tool_version: str
    declared_profile_hash: Digest
    contract_hash: Digest
    resolved_profile_hash: Digest
    timeout_s: int


class FunctionalResponse(StrictModel):
    profile: FunctionalSummary
    candidate_hash: Digest
    outcome: FunctionalOutcome


class FunctionalProfile(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    version: Literal["1"] = "1"
    task_id: str
    top: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    sources: list[str] = Field(min_length=1, max_length=1)
    tool_version: str = "Verilator 5.052"
    docker: DockerRuntimeConfig
    assets: list[Asset] = Field(min_length=3, max_length=64)
    outputs: list[str] = Field(min_length=1, max_length=32)
    timeout_s: int = Field(default=300, ge=1, le=300)

    @field_validator("sources")
    @classmethod
    def source_names(cls, values: list[str]) -> list[str]:
        for value in values:
            Source.source_path(value)
        return values

    @field_validator("outputs")
    @classmethod
    def output_names(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v) is None for v in values
        ):
            raise ValueError("invalid public output names")
        return values

    @model_validator(mode="after")
    def fixed_boundary(self) -> FunctionalProfile:
        if (
            self.docker.expected_image_id is None
            or self.docker.run_as_user is None
            or self.docker.pull_policy != "never"
            or self.docker.external_agent is not None
            or self.docker.command_image is not None
            or self.docker.environment_allowlist
        ):
            raise ValueError("functional flow requires a pinned, credential-free verifier image")
        roles = [a.role for a in self.assets]
        if len(roles) != len(set(roles)) or any(
            relative_path(role) != Path(role).name or Path(role).suffix not in {".v", ".sv"}
            for role in roles
        ):
            raise ValueError("only unique fixed RTL filenames may be staged")
        if not {f"{self.top}_{s}.sv" for s in ("ref", "stimulus_gen", "testbench")} <= set(roles):
            raise ValueError("native functional assets are incomplete")
        if f"{self.top}_top.sv" in roles:
            raise ValueError("the upstream candidate slot cannot be a verifier asset")
        return self

    def summary(self) -> FunctionalSummary:
        for asset in self.assets:
            path = Path(asset.path)
            if path.stat().st_nlink != 1 or hash_bytes(bounded_read(path)) != asset.sha256:
                raise ValueError("functional asset identity mismatch")
        contract = {
            "protocol": PROTOCOL,
            **self.model_dump(mode="json", exclude={"assets"}),
            "assets": [{"role": a.role, "sha256": a.sha256} for a in self.assets],
            "candidate_policy": "single_module_no_side_effects_v1",
            "feedback_policy": "syntax_function_status_only_v1",
        }
        digest = content_hash(contract)
        release = content_hash(
            {
                p.name: hash_bytes(bounded_read(p))
                for p in sorted(Path(__file__).parent.glob("*.py"))
            }
        )
        return FunctionalSummary(
            profile_id=self.id,
            task_id=self.task_id,
            top=self.top,
            sources=self.sources,
            tool_version=self.tool_version,
            declared_profile_hash=digest,
            contract_hash=digest,
            resolved_profile_hash=content_hash({"contract": digest, "release": release}),
            timeout_s=self.timeout_s,
        )


def candidate_is_rtl(candidate: dict[str, bytes], top: str) -> bool:
    """Slice eligibility, not an OS sandbox: reject simulation/report side effects."""
    allowed_calls = {"$clog2", "$bits", "$signed", "$unsigned", "$size"}
    for payload in candidate.values():
        try:
            text = payload.decode("utf-8")
        except UnicodeError:
            return False
        if "\x00" in text or "verilator" in text.lower():
            return False
        text = re.sub(r"/\*.*?\*/|//[^\n]*", " ", text, flags=re.S)
        if "\\" in text or '"' in text:
            return False
        if any(
            call not in allowed_calls for call in re.findall(r"\$[A-Za-z_][A-Za-z0-9_$]*", text)
        ):
            return False
        # No preprocessing interference with private testbench/ref compilation units.
        if any(name != "timescale" for name in re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)", text)):
            return False
        if re.search(r"\b(?:bind|import|export|program|interface|primitive)\b", text):
            return False
        if re.findall(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)", text) != [top]:
            return False
        # Cross-module references could target checker state; hierarchical identifiers are
        # excluded in this derived slice. Named port connections (.port) remain permitted.
        if re.search(r"[A-Za-z0-9_\]\\]\s*\.\s*[A-Za-z_]", text):
            return False
    return True


def parse_simulation(completed: CompletedCommand, outputs: list[str]) -> Status:
    if completed.timed_out:
        return "timeout"
    if completed.error or completed.output_truncated or completed.exit_code != 0:
        return "infrastructure_failure"
    if completed.stderr:
        return "infrastructure_failure"
    observed: dict[str, bool] = {}
    aggregate: bool | None = None
    for line in completed.stdout.splitlines():
        alternate = re.fullmatch(
            r"([A-Za-z_][A-Za-z0-9_]*) has ([1-9][0-9]*) mismatches\. First at time [0-9]+",
            line,
        )
        if alternate is not None:
            name = alternate[1]
            if name == "total":
                if aggregate is not None:
                    return "infrastructure_failure"
                aggregate = False
                continue
            if name not in outputs or name in observed:
                return "infrastructure_failure"
            observed[name] = False
            continue
        if not line.startswith("Hint: Output"):
            continue
        if line == "Hint: Output total has no mismatches.":
            if aggregate is not None:
                return "infrastructure_failure"
            aggregate = True
            continue
        match = re.fullmatch(
            r"Hint: Output '([A-Za-z_][A-Za-z0-9_]*)' has "
            r"(no mismatches\.|[1-9][0-9]* mismatches\. First mismatch occurred at time [0-9]+\.)",
            line,
        )
        if match is None or match[1] not in outputs or match[1] in observed:
            return "infrastructure_failure"
        observed[match[1]] = match[2] == "no mismatches."
    if set(observed) != set(outputs):
        return "infrastructure_failure"
    if aggregate is not None and aggregate != all(observed.values()):
        return "infrastructure_failure"
    return "passed" if all(observed.values()) else "function_failed"


def compile_command(profile: FunctionalProfile) -> CommandSpec:
    return CommandSpec(
        argv=[
            "verilator",
            "--binary",
            "--timing",
            "--assert",
            "-fno-table",
            "-j",
            "2",
            "--top-module",
            "tb",
            "--Mdir",
            ".verigym_internal/build",
            *[f"-Wno-{w}" for w in _WARNINGS],
            *[f"verification/{a.role}" for a in profile.assets],
            *profile.sources,
        ],
        timeout_s=profile.timeout_s,
    )


def run_functional(
    profile: FunctionalProfile, candidate: dict[str, bytes] | None
) -> FunctionalOutcome:
    """Each call owns a new isolated session; cleanup must complete before a verdict returns."""
    profile.summary()
    if profile.docker.run_as_user != f"{os.getuid()}:{os.getgid()}":
        return FunctionalOutcome(
            status="infrastructure_failure", cleanup_complete=True, phase="prepare"
        )
    if candidate is not None and (
        list(candidate) != profile.sources or not candidate_is_rtl(candidate, profile.top)
    ):
        return FunctionalOutcome(status="compile_failed", cleanup_complete=True)
    runtime = DockerRuntime(profile.docker)
    status: Status = "infrastructure_failure"
    phase: Literal["policy", "prepare", "probe", "compile", "simulate", "cleanup"] = "prepare"
    exit_code = None
    try:
        runtime.prepare(f"realbench-functional-{uuid.uuid4().hex}")
        with tempfile.TemporaryDirectory(prefix="rb-functional-") as empty:
            if candidate is not None:
                staged = {
                    f"verification/{a.role}": bounded_read(Path(a.path)) for a in profile.assets
                }
                if any(
                    hash_bytes(staged[f"verification/{a.role}"]) != a.sha256 for a in profile.assets
                ):
                    raise ValueError("functional asset drift")
                for relative, payload in {**staged, **candidate}.items():
                    path = Path(empty) / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
            with closing(
                runtime.create_session(
                    SessionSpec(
                        source_dir=empty,
                        label="verifier",
                        max_output_bytes=2 * 1024 * 1024,
                    )
                )
            ) as session:
                phase = "probe"
                probe = session.execute(CommandSpec(argv=["verilator", "--version"], timeout_s=30))
                exit_code = probe.exit_code
                if (
                    probe.exit_code != 0
                    or probe.error
                    or probe.output_truncated
                    or not probe.stdout.startswith(profile.tool_version + " ")
                ):
                    raise ValueError("Verilator identity mismatch")
                if candidate is None:
                    for tool in ("g++", "make"):
                        result = session.execute(
                            CommandSpec(argv=[tool, "--version"], timeout_s=30)
                        )
                        if result.exit_code != 0 or result.error or result.output_truncated:
                            raise ValueError("functional build tool unavailable")
                    status = "passed"
                else:
                    phase = "compile"
                    result = session.execute(compile_command(profile))
                    exit_code = result.exit_code
                    if result.timed_out:
                        status = "timeout"
                    elif result.error or result.output_truncated:
                        status = "infrastructure_failure"
                    elif result.exit_code != 0:
                        # Only diagnostics located in candidate sources count as a rejection.
                        status = (
                            "compile_failed"
                            if any(
                                re.search(
                                    r"^%(?:Error|Warning)(?:-[A-Z0-9_]+)?: "
                                    + re.escape(p)
                                    + r":[0-9]+:",
                                    result.stderr,
                                    re.M,
                                )
                                for p in candidate
                            )
                            else "infrastructure_failure"
                        )
                    else:
                        phase = "simulate"
                        result = session.execute(
                            CommandSpec(
                                argv=["build/Vtb"],
                                cwd=".verigym_internal",
                                timeout_s=profile.timeout_s,
                            )
                        )
                        exit_code = result.exit_code
                        status = parse_simulation(result, profile.outputs)
                    profile.summary()
    except Exception:
        status = "infrastructure_failure"
    finally:
        runtime.close()
    cleanup = runtime.descriptor.cleanup
    complete = cleanup is not None and cleanup.complete
    if not complete:
        status = "infrastructure_failure"
        phase = "cleanup"
    return FunctionalOutcome(
        status=status, cleanup_complete=complete, phase=phase, exit_code=exit_code
    )
