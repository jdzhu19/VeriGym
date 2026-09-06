"""Trusted-fixture Yosys -> JasperGold worker, launched by a private fixed site wrapper.

This is not a sandbox. Both entry points require a pre-audited candidate hash. Real generated
RTL requires a separately qualified isolation boundary, not removal of this check.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from verigym.plugin_api import CommandSpec, CompletedCommand
from verigym.runtimes.local import LocalRuntime, LocalRuntimeSession
from verigym.schemas.runtime import SessionSpec

from .protocol import (
    LICENSE_ENVIRONMENT_NAMES,
    MAX_REQUEST_BYTES,
    Outcome,
    ServerProfile,
    VerifyRequest,
    bounded_read,
    relative_path,
    unique_json,
)


def parse_sec(completed: CompletedCommand, log: str) -> Outcome:
    if completed.timed_out:
        return Outcome(status="timeout")
    if completed.error or completed.output_truncated:
        return Outcome(status="infrastructure_failure")
    text = completed.stdout + "\n" + completed.stderr + "\n" + log
    if re.search(r"license.*(?:fail|unavailable|denied)|unable to.*license", text, re.I):
        return Outcome(status="license_unavailable")
    if completed.exit_code != 0:
        return Outcome(status="infrastructure_failure")
    results = re.findall(r"^JPW:\s*(\S+)\s*$", log, re.M)
    if len(results) != 1:
        return Outcome(status="infrastructure_failure")
    if results[0] == "proven":
        return Outcome(status="proven")
    if results[0] in {"cex", "cex_threshold_reached"}:
        return Outcome(status="counterexample")
    if results[0] in {"determined", "determined_or_skipped", "undetermined", "inconclusive"}:
        return Outcome(status="inconclusive")
    return Outcome(status="infrastructure_failure")


def _execute(session: LocalRuntimeSession, argv: list[str], timeout: int) -> CompletedCommand:
    environment = {
        name: os.environ[name] for name in LICENSE_ENVIRONMENT_NAMES if name in os.environ
    }
    return session.execute(CommandSpec(argv=argv, timeout_s=timeout, env=environment))


def run(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"operation", "profile", "request"}:
        raise ValueError("invalid worker envelope")
    profile = ServerProfile.model_validate(payload["profile"])
    summary = profile.resolve()
    assets = {a.role: Path(a.path) for a in profile.assets}
    jg, yosys = assets["jaspergold"], assets["yosys"]
    with tempfile.TemporaryDirectory(prefix="jg-native-") as empty:
        with LocalRuntime().create_session(
            SessionSpec(
                source_dir=empty,
                label="jg-native",
                max_output_bytes=1024 * 1024,
            )
        ) as session:
            jg_version = _execute(session, [str(jg), "-version"], 20)
            yosys_version = _execute(session, [str(yosys), "-V"], 20)
            if any(
                result.exit_code != 0 or result.timed_out or result.error or result.output_truncated
                for result in (jg_version, yosys_version)
            ):
                return {"status": "tool_unavailable"}
            jg_match = re.search(
                r"\b(20\d\d\.\d\d(?:p\d+)?(?:-[A-Za-z0-9._-]+)?)\b",
                jg_version.stdout + jg_version.stderr,
            )
            yosys_match = re.search(r"\bYosys\s+(\S+)", yosys_version.stdout + yosys_version.stderr)
            if jg_match is None or yosys_match is None:
                return {"status": "tool_unavailable"}
            versions = {"tool_version": jg_match[1], "yosys_version": yosys_match[1]}
            if versions != {
                "tool_version": profile.tool_version,
                "yosys_version": profile.yosys_version,
            }:
                return {"status": "tool_unavailable"}
            if payload["operation"] == "probe" and payload["request"] is None:
                return versions
            if payload["operation"] != "verify":
                raise ValueError("invalid operation")
            request = VerifyRequest.model_validate(payload["request"])
            candidate = request.candidate()
            if (
                request.task_id != profile.task_id
                or request.top != profile.top
                or request.profile_id != profile.id
                or request.contract_hash != summary.contract_hash
                or request.declared_profile_hash != summary.declared_profile_hash
                or request.expected_resolved_profile_hash != summary.resolved_profile_hash
                or request.candidate_hash not in profile.approved_candidate_hashes
                or list(candidate) != profile.sources
            ):
                raise ValueError("candidate not approved for trusted-fixture execution")
            ref_sources: list[str] = []
            imp_sources: list[str] = []
            for role, path in assets.items():
                if role.startswith(("reference:", "dependency:")):
                    kind, name = role.split(":", 1)
                    relative_path(name)
                    for prefix in ["ref", "imp"] if kind == "dependency" else ["ref"]:
                        destination = session.root / prefix / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if destination.exists():
                            raise ValueError("duplicate verifier source destination")
                        destination.write_bytes(bounded_read(path))
                        (ref_sources if prefix == "ref" else imp_sources).append(f"{prefix}/{name}")
            if not ref_sources:
                raise ValueError("reference inputs missing")
            for name, contents in candidate.items():
                destination = session.root / "imp" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise ValueError("candidate collides with verifier dependency")
                destination.write_bytes(contents)
                imp_sources.append(f"imp/{name}")
            for kind, sources, top, netlist in [
                ("reference", ref_sources, f"ref_{profile.top}", "a.v"),
                ("candidate", imp_sources, profile.top, "b.v"),
            ]:
                result = _execute(
                    session,
                    [
                        str(yosys),
                        "-p",
                        f"read_verilog -sv {' '.join(sources)}; hierarchy -check -top {top}; "
                        f"synth -top {top}; write_verilog {netlist}",
                    ],
                    profile.timeout_s,
                )
                if result.timed_out:
                    return {"status": "timeout"}
                if result.error or result.output_truncated:
                    return {"status": "infrastructure_failure"}
                if result.exit_code != 0:
                    return {
                        "status": "candidate_compile_failure"
                        if kind == "candidate"
                        else "infrastructure_failure"
                    }
            template = bounded_read(assets["sec_template"]).decode("utf-8")
            if "###TOPMODULE###" not in template:
                raise ValueError("SEC template top binding is missing")
            (session.root / "test.tcl").write_text(
                template.replace("###TOPMODULE###", profile.top), encoding="utf-8"
            )
            (session.root / "ref.f").write_text("a.v\n", encoding="ascii")
            (session.root / "top.f").write_text("b.v\n", encoding="ascii")
            result = _execute(session, [str(jg), "-no_gui", "-sec", "test.tcl"], profile.timeout_s)
            log_path = session.root / "jgproject" / "jg.log"
            log = (
                bounded_read(log_path).decode("utf-8", errors="replace")
                if log_path.exists()
                else ""
            )
            return parse_sec(result, log).model_dump()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("oversized worker request")
        result = run(unique_json(raw.decode("utf-8")))
    except Exception:
        result = {"status": "infrastructure_failure"}
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
