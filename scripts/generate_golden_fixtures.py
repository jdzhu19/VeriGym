"""Regenerate sanitized schema-1.0 compatibility fixtures.

This maintainer-only command runs first-party local fixtures. It never copies
hidden sources or external benchmark contents into the golden directory.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path
from typing import Any

from verigym.api import BatchRunner, ExperimentConfig, ExperimentPlanner, RunConfig, VeriGym
from verigym.core.hashing import content_hash
from verigym.profiles.base import (
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
)
from verigym.registry import build_registries
from verigym.schemas.common import RuntimeDescriptor
from verigym.schemas.run import RunResult
from verigym.schemas.score import PPAMetrics, QualityMetrics
from verigym.schemas.suite import SuiteSourceConfig
from verigym.schemas.synthesis import SynthesisMetrics

_FIXED_TIME = "2026-01-01T00:00:00Z"
_OUTPUT = Path("tests/fixtures/golden/v1")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sanitized_run(result: RunResult, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = result.manifest.model_dump(mode="json")
    manifest["run_id"] = run_id
    manifest["created_at_utc"] = _FIXED_TIME
    manifest["verigym_commit"] = None
    manifest.pop("build_provenance", None)
    manifest.pop("model_observations", None)
    manifest["run_config_hash"] = content_hash({"legacy_fixture": run_id})
    manifest["environment_summary"] = {
        "network_policy": "none",
        "platform": "sanitized",
        "python": "3.11",
        "python_implementation": "CPython",
        "unsafe_local_runtime": True,
        "verifier_isolation": "separate_runtime_session",
    }

    score = result.scorecard.model_dump(mode="json")
    score["run_id"] = run_id
    score["efficiency"].update(
        {
            "wall_time_s": 0.0,
            "agent_time_s": 0.0,
            "tool_time_s": 0.0,
            "verifier_time_s": 0.0,
        }
    )
    score["efficiency"].pop("model_api_cost_currency", None)
    score["efficiency"].pop("model_api_cost_unit", None)
    score["reproducibility"]["run_config_hash"] = manifest["run_config_hash"]
    for verifier in score["verifier_results"]:
        verifier["duration_s"] = 0.0
    return manifest, score


def _docker_manifest(local_manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads(json.dumps(local_manifest))
    manifest["run_id"] = "golden-docker-replay"
    manifest["runtime"] = RuntimeDescriptor.model_validate(
        {
            "schema_version": "1.0",
            "name": "docker",
            "version": "0.1.0",
            "api_version": "1.0",
            "provider": "verigym",
            "capabilities": ["cli", "network_none", "resource_limits"],
            "isolation_level": "docker_standard",
            "deterministic": True,
            "backend": {
                "backend_type": "docker_cli",
                "client_version": "23.0.4",
                "server_version": "23.0.4",
                "api_version": "1.42",
                "server_os": "linux",
                "server_architecture": "amd64",
                "rootless": False,
            },
            "image": {
                "requested_reference": "example.invalid/verigym/iverilog@sha256:" + "1" * 64,
                "resolved_image_id": "sha256:" + "1" * 64,
                "repository_digests": ["example.invalid/verigym/iverilog@sha256:" + "1" * 64],
                "os": "linux",
                "architecture": "amd64",
                "configured_image_user": "10001:10001",
                "effective_user": "10001:10001",
                "observed_uid": 10001,
                "observed_gid": 10001,
                "iverilog_version": "Icarus Verilog version 12.0",
                "vvp_version": "Icarus Verilog runtime version 12.0",
                "compatibility_status": "reference_compatible",
            },
            "security": {
                "network_mode": "none",
                "read_only_rootfs": True,
                "configured_user": "10001:10001",
                "observed_uid": 10001,
                "observed_gid": 10001,
                "privileged": False,
                "cap_drop": ["ALL"],
                "no_new_privileges": True,
                "init": True,
                "mount_destinations": ["/workspace"],
                "writable_destinations": ["/workspace", "/tmp"],
                "environment_names": [],
                "docker_socket_mounted": False,
                "host_home_mounted": False,
            },
            "resources": {
                "memory_bytes": 536870912,
                "memory_swap_bytes": 536870912,
                "swap_enforced": True,
                "cpus": 1.0,
                "pids_limit": 128,
                "tmpfs_bytes": 67108864,
                "stop_timeout_s": 3,
                "max_command_time_s": 60,
                "max_output_bytes": 200000,
            },
            "sessions": [],
            "cleanup": {"complete": True, "removed_container_ids": [], "warnings": []},
            "configuration_fingerprint": "2" * 64,
        }
    ).model_dump(mode="json")
    manifest["environment_summary"]["unsafe_local_runtime"] = False
    return manifest


def _resolved_profile() -> ResolvedToolchainProfile:
    return ResolvedToolchainProfile(
        profile_id="open-yosys-toy-area-v1",
        profile_version="1.0.0",
        declared_profile_hash="d" * 64,
        resolved_profile_hash="a" * 64,
        reproducibility_scope="public",
        deterministic=True,
        runtime_identity=ResolvedRuntimeIdentity(
            runtime_slug="docker",
            isolation_level="docker_standard",
            deterministic=True,
            os="linux",
            architecture="amd64",
            requested_image_reference="verigym/open-rtl-tools:audited",
            resolved_image_id="sha256:" + "3" * 64,
            network_policy="none",
            resource_controls=True,
            security_hash="4" * 64,
            resource_contract_hash="5" * 64,
        ),
        tool_identities=[
            ResolvedToolIdentity(
                logical_name="yosys",
                executable="yosys",
                version="0.67",
                version_output="Yosys 0.67 (audited fixture)",
                git_hash="b8e7da6f40ae8f552c116bf6c359b07c6533e159",
                capabilities=["synth", "stat_json", "liberty", "abc"],
                identity_kind="immutable_image_observation",
            ),
            ResolvedToolIdentity(
                logical_name="yosys-abc",
                executable="yosys-abc",
                version="1.01",
                version_output="ABC 1.01 (audited fixture)",
                git_hash="e026ed5380f3bdc3beea2ff9ffc23236fc549d5b",
                capabilities=["liberty_mapping"],
                identity_kind="immutable_image_observation",
            ),
        ],
        asset_identities=[
            ResolvedArtifactIdentity(
                logical_id="verigym-toy-cells-v1",
                media_type="application/x-liberty",
                source_kind="package_resource",
                content_hash="817685fa394822882602ca0469065f0d5db6ee52a07788d16ff8f84ebb536512",
                license="Apache-2.0",
                attribution="Copyright 2026 VeriGym contributors",
                redistributable=True,
                unit="toy_area_unit",
                semantics="educational profile-relative non-signoff area",
                copy_permitted=True,
                replay_locator="verigym.profiles.builtins:assets/toy_cells.lib",
            )
        ],
        flow_hash="6" * 64,
        metric_contract_hash="7" * 64,
        reference_contract_hash="8" * 64,
        flow_template_id="verigym-yosys-area-v1",
        generated_script_hash="b" * 64,
        top_module="counter",
        source_paths=["rtl/counter.v"],
        metric_scope="synthesis_area_only",
        area_unit="toy_area_unit",
        reference_strategy="suite_reference_solution",
        reference_candidate_hash="c" * 64,
    )


def _yosys_score(base: dict[str, Any]) -> dict[str, Any]:
    candidate = SynthesisMetrics(
        status="passed",
        synthesis_ok=True,
        role="candidate",
        top="counter",
        num_wires=31,
        num_wire_bits=38,
        num_memories=0,
        num_memory_bits=0,
        num_processes=0,
        num_cells=36,
        cells_by_type={"VG_AND2": 7, "VG_DFF": 8},
        mapped_area_raw=90.0,
        mapped_area_unit="toy_area_unit",
        mapped_area_source_hash="9" * 64,
        resolved_profile_hash="a" * 64,
        generated_script_hash="b" * 64,
    )
    reference = candidate.model_copy(
        update={
            "role": "reference",
            "num_wires": 30,
            "num_wire_bits": 37,
            "num_cells": 35,
            "cells_by_type": {"VG_AND2": 6, "VG_DFF": 8},
            "mapped_area_raw": 87.0,
        }
    )
    payload = json.loads(json.dumps(base))
    payload["quality"] = QualityMetrics(
        ppa=PPAMetrics(
            profile_id="open-yosys-toy-area-v1",
            profile_version="1.0.0",
            resolved_profile_hash="a" * 64,
            eligible=True,
            area=90.0,
            area_unit="toy_area_unit",
            reference_area=87.0,
            area_ratio=87.0 / 90.0,
        ),
        synthesis=candidate,
        reference_synthesis=reference,
    ).model_dump(mode="json")
    payload["reproducibility"]["resolved_toolchain_profile_hashes"] = ["a" * 64]
    payload["reproducibility"]["toolchain_profile_ids"] = ["open-yosys-toy-area-v1"]
    payload["warnings"] = [
        "Synthesis quality is educational, profile-relative, area-only, and non-signoff."
    ]
    return payload


def _legacy(payload: dict[str, Any], *fields: str) -> dict[str, Any]:
    result = json.loads(json.dumps(payload))
    for field in fields:
        result.pop(field, None)
    return result


def main() -> None:
    registries = build_registries(discover_external=False)
    service = VeriGym(registries)
    with tempfile.TemporaryDirectory(prefix="verigym-golden-source-") as temporary:
        root = Path(temporary)
        resolved = service.run(
            RunConfig(
                task_id="toy-rtl/and-gate-basic",
                agent="scripted",
                output=root / "resolved",
            )
        )
        unresolved = service.run(
            RunConfig(
                task_id="toy-rtl/and-gate-basic",
                agent="scripted-bad",
                output=root / "unresolved",
            )
        )
        model_error = service.run(
            RunConfig(
                task_id="toy-rtl/and-gate-basic",
                mode="chat",
                agent="single-turn",
                model="static-exhausted",
                output=root / "model-error",
            )
        )
        counter = service.run(
            RunConfig(
                task_id="toy-rtl/counter-basic",
                agent="scripted",
                output=root / "counter",
            )
        )

        resolved_manifest, resolved_score = _sanitized_run(resolved, "golden-resolved-local")
        unresolved_manifest, unresolved_score = _sanitized_run(
            unresolved, "golden-unresolved-normal"
        )
        error_manifest, error_score = _sanitized_run(model_error, "golden-model-error")
        counter_manifest, counter_score = _sanitized_run(counter, "golden-yosys-area")
        del unresolved_manifest, error_manifest, counter_manifest

        _write_json(
            _OUTPUT / "resolved_local" / "run_manifest.json",
            _legacy(resolved_manifest, "build_provenance", "model_observations"),
        )
        _write_json(
            _OUTPUT / "resolved_local" / "scorecard.json",
            _legacy_score(resolved_score),
        )
        _write_json(
            _OUTPUT / "unresolved_normal" / "scorecard.json",
            _legacy_score(unresolved_score),
        )
        _write_json(
            _OUTPUT / "model_error" / "scorecard.json",
            _legacy_score(error_score),
        )
        _write_json(
            _OUTPUT / "docker_replay" / "run_manifest.json",
            _docker_manifest(resolved_manifest),
        )
        _write_json(
            _OUTPUT / "yosys_area" / "scorecard.json",
            _legacy_score(_yosys_score(counter_score)),
        )
        _write_json(
            _OUTPUT / "yosys_area" / "resolved_toolchain_profile.json",
            _resolved_profile().model_dump(mode="json"),
        )

        source = SuiteSourceConfig(
            source_root=(Path("tests/fixtures/verilog_eval_v2_synthetic").resolve()),
            variant="v2-spec-to-rtl",
            strict_compatibility=True,
        )
        sample_set = service.run_samples(
            RunConfig(
                task_id="verilog-eval/Prob900_fixture_and",
                mode="chat",
                agent="single-turn",
                model="static-verilog-eval-fixture-mixed",
                suite_source=source,
                output=root / "samples",
            ),
            samples=2,
            pass_k=[1, 2],
        )
        sample_manifest = sample_set.manifest.model_dump(mode="json")
        sample_report = sample_set.report.model_dump(mode="json")
        sample_manifest["sample_set_id"] = "golden-verilog-eval-samples"
        sample_manifest["created_at_utc"] = _FIXED_TIME
        sample_manifest.pop("build_provenance", None)
        sample_report["sample_set_id"] = "golden-verilog-eval-samples"
        for index, child in enumerate(sample_manifest["child_runs"]):
            child["run_id"] = f"golden-verilog-eval-{index}"
            child["relative_path"] = f"samples/{index:04d}/golden-verilog-eval-{index}"
        sample_report["child_runs"] = sample_manifest["child_runs"]
        _write_json(
            _OUTPUT / "verilog_eval_sampling" / "sample_set_manifest.json",
            sample_manifest,
        )
        _write_json(
            _OUTPUT / "verilog_eval_sampling" / "pass_at_k.json",
            sample_report,
        )

        config = ExperimentConfig.model_validate(
            {
                "schema_version": "1.0",
                "name": "golden-milestone9",
                "suite": {
                    "id": "toy-rtl",
                    "tasks": {"include": ["and-gate-basic"], "exclude": []},
                },
                "runs": {
                    "mode": "agent",
                    "seeds": [0],
                    "samples_per_task": 1,
                    "pass_k": [1],
                },
                "systems": [{"id": "scripted", "agent": {"id": "scripted"}}],
                "runtime": {"id": "local"},
                "execution": {"max_workers": 1},
                "output": {"root": root / "experiment"},
            }
        )
        planner = ExperimentPlanner(service)
        experiment = BatchRunner(planner=planner, service_factory=lambda: service).run(
            planner.build(config)
        )
        experiment_root = experiment.experiment_dir
        fixture_root = _OUTPUT / "experiment"
        manifest = json.loads(
            (experiment_root / "experiment_manifest.json").read_text(encoding="utf-8")
        )
        manifest["created_at_utc"] = _FIXED_TIME
        manifest["verigym_commit"] = None
        manifest.pop("build_provenance", None)
        _write_json(fixture_root / "experiment_manifest.json", manifest)
        stored_config = json.loads(
            (experiment_root / "experiment_config.json").read_text(encoding="utf-8")
        )
        stored_config["execution"].pop("max_plan_items", None)
        _write_json(fixture_root / "experiment_config.json", stored_config)
        plan_row = json.loads(
            (experiment_root / "plan.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        (fixture_root / "plan.jsonl").write_text(
            json.dumps(plan_row, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        index_row = json.loads(
            (experiment_root / "run_index.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        old_run_id = index_row["child_run_id"]
        index_row["child_run_id"] = "golden-experiment-child"
        index_row["relative_child_path"] = "runs/golden-experiment-child"
        index_row.pop("artifact_manifest_hash", None)
        (fixture_root / "run_index.jsonl").write_text(
            json.dumps(index_row, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        aggregate = json.loads(
            (experiment_root / "reports" / "aggregate.json").read_text(encoding="utf-8")
        )
        aggregate.pop("build_provenance", None)
        aggregate.pop("cost_accounting", None)
        aggregate["efficiency_resolved"]["wall_time_s"]["mean"] = 0.0
        aggregate["efficiency_resolved"]["wall_time_s"]["median"] = 0.0
        _write_json(fixture_root / "aggregate.json", aggregate)
        csv_text = (experiment_root / "reports" / "runs.csv").read_text(encoding="utf-8")
        csv_text = csv_text.replace(str(old_run_id), "golden-experiment-child")
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        for row in rows:
            row["wall_time_s"] = "0"
        csv_output = io.StringIO(newline="")
        writer = csv.DictWriter(csv_output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        (fixture_root / "runs.csv").write_text(csv_output.getvalue(), encoding="utf-8")
        markdown = (experiment_root / "reports" / "report.md").read_text(encoding="utf-8")
        markdown = markdown.replace(str(old_run_id), "golden-experiment-child")
        markdown = (
            "\n".join(
                (
                    "| wall_time_s | 1 | 0 | 0 | 0 | seconds |"
                    if line.startswith("| wall_time_s |")
                    else line
                )
                for line in markdown.splitlines()
            )
            + "\n"
        )
        (fixture_root / "report.md").write_text(markdown, encoding="utf-8")


def _legacy_score(payload: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(payload))
    result["efficiency"].pop("model_api_cost_currency", None)
    result["efficiency"].pop("model_api_cost_unit", None)
    return result


if __name__ == "__main__":
    main()
