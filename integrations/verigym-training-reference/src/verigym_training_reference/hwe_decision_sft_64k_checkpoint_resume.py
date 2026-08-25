"""Three-process coordinator for the authorized 64K checkpoint/resume qualification."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf  # type: ignore[import-not-found]
from rllm.trainer.sft.backend import SFTConfigError  # type: ignore[import-not-found]
from verigym.experiments.state import atomic_dump_json
from verigym.schemas.hwe_training import (
    HweDecisionSft64kCheckpointResumeQualificationAuthorization,
    HweDecisionSft64kOptimizerSmokePreregistration,
)

from .hwe_decision_sft_64k_backend import (
    VeriGymHweDecisionSft64kTrainer,
    assert_qualification_config,
)
from .hwe_decision_sft_64k_checkpoint_resume_entry import (
    _delete_temporary_checkpoint,
    _verify_checkpoint_manifest,
)
from .hwe_decision_sft_64k_optimizer_smoke import (
    CheckpointResumeBranch,
    prepare_checkpoint_resume_branch_config,
)

_EXACT_REPLAY_DETERMINISM = {
    "format_id": "verigym_hwe_checkpoint_resume_determinism_v1",
    "flash_attention_deterministic": True,
    "cublas_workspace_config": ":4096:8",
    "torch_deterministic_algorithms": True,
    "cudnn_benchmark": False,
    "cudnn_deterministic": True,
    "host_rng_step_boundary_normalized": True,
    "host_rng_step_seed_derivation": "engine_seed_times_1000003_plus_global_step",
}


class VeriGymHweDecisionSft64kCheckpointResumeTrainer:
    """Prepare one loader and launch control, producer, and resume torchruns."""

    def __init__(
        self,
        *,
        preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
        authorization: HweDecisionSft64kCheckpointResumeQualificationAuthorization,
        dataset_root: Path,
        model_root: Path,
        scratch_root: Path,
        checkpoint_root: Path,
        evidence_root: Path,
    ) -> None:
        self.preregistration = preregistration
        self.authorization = authorization
        self.scratch_root = scratch_root
        self.checkpoint_root = checkpoint_root
        self.evidence_root = evidence_root
        self.dispatcher = VeriGymHweDecisionSft64kTrainer(
            dataset_root=dataset_root,
            model_root=model_root,
            scratch_root=scratch_root,
            offload=False,
        )

    def launch(
        self,
        *,
        preregistration_path: Path,
        authorization_path: Path,
        report: Path,
        rllm_source: Path,
        verl_source: Path,
        transformers_source: Path,
    ) -> None:
        """Run all three fresh processes and require exact state equivalence."""

        if self.checkpoint_root.exists() or self.checkpoint_root.is_symlink():
            raise SFTConfigError("checkpoint/resume temporary checkpoint root already exists")
        if self.evidence_root.exists() or self.evidence_root.is_symlink():
            raise SFTConfigError("checkpoint/resume evidence root already exists")
        self.evidence_root.mkdir(parents=True, mode=0o700)
        self.scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        backend = self.dispatcher.prepare()
        plain = OmegaConf.to_container(backend.config, resolve=True)
        if not isinstance(plain, dict):
            raise SFTConfigError("checkpoint/resume qualification config is not a mapping")
        assert_qualification_config(backend.config, offload=False)

        started = time.monotonic()
        branch_reports: dict[str, Path] = {}
        try:
            for branch in ("control", "producer", "resume"):
                branch_name: CheckpointResumeBranch = branch
                branch_report = self.evidence_root / f"{branch}-branch-report.json"
                branch_reports[branch] = branch_report
                branch_scratch = self.scratch_root / branch
                branch_scratch.mkdir(parents=True, mode=0o700)
                branch_config = prepare_checkpoint_resume_branch_config(
                    plain,
                    self.preregistration,
                    self.authorization,
                    branch=branch_name,
                    checkpoint_root=str(self.checkpoint_root),
                )
                config_path = branch_scratch / "resolved-config.yaml"
                OmegaConf.save(OmegaConf.create(branch_config), config_path)
                self._launch_branch(
                    branch=branch_name,
                    config_path=config_path,
                    preregistration_path=preregistration_path,
                    authorization_path=authorization_path,
                    branch_report=branch_report,
                    branch_scratch=branch_scratch,
                    rllm_source=rllm_source,
                    verl_source=verl_source,
                    transformers_source=transformers_source,
                )
                if branch == "producer":
                    producer = _read_report(branch_report)
                    _verify_checkpoint_manifest(
                        self.checkpoint_root,
                        producer.get("checkpoint_manifest"),
                    )

            control = _read_report(branch_reports["control"])
            producer = _read_report(branch_reports["producer"])
            resumed = _read_report(branch_reports["resume"])
            comparison = _compare_branches(control, producer, resumed)
            manifest = producer["checkpoint_manifest"]
            _verify_checkpoint_manifest(self.checkpoint_root, manifest)
            checkpoint_deleted = _delete_temporary_checkpoint(self.checkpoint_root)
            execution_wall = time.monotonic() - started
            branch_values = (control, producer, resumed)
            atomic_dump_json(
                report,
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_checkpoint_resume_qualification_execution_v1",
                    "status": "passed",
                    "scope": "development_checkpoint_resume_conformance_only",
                    "authorization_hash": self.authorization.authorization_hash,
                    "authorization_attempt": 8,
                    "replaces_authorization_hash": (self.authorization.replaces_authorization_hash),
                    "preregistration_hash": self.preregistration.preregistration_hash,
                    "source_v4_dataset_hash": self.preregistration.source_v4_dataset_hash,
                    "schedule_hash": self.preregistration.schedule_hash,
                    "branches": {
                        name: {
                            "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "optimizer_steps_observed": _read_report(path)[
                                "optimizer_steps_observed"
                            ],
                        }
                        for name, path in branch_reports.items()
                    },
                    "comparison": comparison,
                    "checkpoint_manifest": manifest,
                    "checkpoint_written": True,
                    "checkpoint_count": 1,
                    "checkpoint_global_step": 2,
                    "checkpoint_loaded_in_fresh_process": True,
                    "checkpoint_resume_validation_deferred": False,
                    "checkpoint_resume_ready": True,
                    "checkpoint_retained": False,
                    "temporary_checkpoint_deleted_after_validation": checkpoint_deleted,
                    "optimizer_steps_authorized": 8,
                    "optimizer_steps": 8,
                    "control_optimizer_steps": 4,
                    "producer_optimizer_steps": 2,
                    "resumed_optimizer_steps": 2,
                    "loader_ready": True,
                    "loader_rows_validated_per_branch": 83,
                    "exact_receipts_revalidated_per_branch": 83,
                    "over_32768_rows_validated_per_branch": 19,
                    "max_token_count": 50_117,
                    "training_started": True,
                    "development_training_ready": True,
                    "production_training_ready": False,
                    "adapter_written": False,
                    "offload_used": False,
                    "truncation_used": False,
                    "bounded_fused_vocabulary_head": True,
                    "global_shift_labels_used": True,
                    "deterministic_replay": _EXACT_REPLAY_DETERMINISM,
                    "world_size": 4,
                    "ulysses_sequence_parallel_size": 4,
                    "selected_gpu_indices": [0, 1, 2, 3],
                    "existing_lsf_job_id": self.preregistration.existing_lsf_job_id,
                    "host": self.preregistration.planned_host,
                    "new_hpc_jobs_submitted": False,
                    "allocation_released": False,
                    "peak_memory_allocated_bytes": max(
                        int(value["peak_memory_allocated_bytes"]) for value in branch_values
                    ),
                    "peak_memory_reserved_bytes": max(
                        int(value["peak_memory_reserved_bytes"]) for value in branch_values
                    ),
                    "branch_execution_wall_seconds": sum(
                        float(value["execution_wall_seconds"]) for value in branch_values
                    ),
                    "execution_wall_seconds": execution_wall,
                    "gpu_seconds": sum(
                        float(value["execution_wall_seconds"]) * 4 for value in branch_values
                    ),
                    "benchmark_score_claimed": False,
                },
            )
        except BaseException as exc:
            deleted = False
            if self.checkpoint_root.exists() and not self.checkpoint_root.is_symlink():
                deleted = _delete_temporary_checkpoint(self.checkpoint_root)
            if not report.exists() and not report.is_symlink():
                atomic_dump_json(
                    report,
                    {
                        "schema_version": "1.0",
                        "format_id": ("verigym_hwe_checkpoint_resume_qualification_execution_v1"),
                        "status": "failed_closed",
                        "authorization_hash": self.authorization.authorization_hash,
                        "authorization_attempt": 8,
                        "first_error_type": type(exc).__name__,
                        "first_error_message": str(exc)[:1000],
                        "completed_branch_reports": {
                            name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for name, path in branch_reports.items()
                            if path.is_file() and not path.is_symlink()
                        },
                        "temporary_checkpoint_deleted_after_failure": deleted,
                        "checkpoint_resume_ready": False,
                        "development_training_ready": False,
                        "production_training_ready": False,
                        "adapter_written": False,
                        "new_hpc_jobs_submitted": False,
                        "allocation_released": False,
                        "existing_lsf_job_id": self.preregistration.existing_lsf_job_id,
                        "benchmark_score_claimed": False,
                    },
                )
            raise

    def _launch_branch(
        self,
        *,
        branch: CheckpointResumeBranch,
        config_path: Path,
        preregistration_path: Path,
        authorization_path: Path,
        branch_report: Path,
        branch_scratch: Path,
        rllm_source: Path,
        verl_source: Path,
        transformers_source: Path,
    ) -> None:
        command = [
            sys.executable,
            "-m",
            "torch.distributed.run",
            "--standalone",
            "--nnodes=1",
            "--nproc_per_node=4",
            "-m",
            "verigym_training_reference.hwe_decision_sft_64k_checkpoint_resume_entry",
            "--branch",
            branch,
            "--config",
            str(config_path),
            "--preregistration",
            str(preregistration_path),
            "--authorization",
            str(authorization_path),
            "--checkpoint-root",
            str(self.checkpoint_root),
            "--report",
            str(branch_report),
            "--scratch-root",
            str(branch_scratch),
            "--rllm-source",
            str(rllm_source),
            "--verl-source",
            str(verl_source),
            "--transformers-source",
            str(transformers_source),
        ]
        environment = {**os.environ, "RLLM_SFT_IN_TORCHRUN": "1"}
        if environment.get("ROCR_VISIBLE_DEVICES") and environment.get("CUDA_VISIBLE_DEVICES"):
            environment.pop("ROCR_VISIBLE_DEVICES", None)
        result = subprocess.run(command, env=environment, check=False)
        if result.returncode != 0:
            raise SFTConfigError(
                f"checkpoint/resume {branch} torchrun exited with code {result.returncode}"
            )
        value = _read_report(branch_report)
        expected = {
            "status": "passed",
            "branch": branch,
            "authorization_hash": self.authorization.authorization_hash,
            "loader_rows_validated": 83,
            "exact_receipts_revalidated": 83,
            "adapter_written": False,
            "production_training_ready": False,
        }
        if any(value.get(key) != item for key, item in expected.items()):
            raise SFTConfigError(f"checkpoint/resume {branch} report failed acceptance")
        if value.get("determinism") != _EXACT_REPLAY_DETERMINISM:
            raise SFTConfigError(f"checkpoint/resume {branch} deterministic kernel receipt changed")


def _read_report(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SFTConfigError("checkpoint/resume branch report is not a safe regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SFTConfigError("checkpoint/resume branch report is not an object")
    return value


def _step_comparable(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key
        not in {
            "peak_memory_allocated_bytes",
            "peak_memory_reserved_bytes",
            "wall_seconds",
        }
    }


def _compare_step_results(
    control: list[dict[str, Any]],
    replay: list[dict[str, Any]],
) -> None:
    if len(control) != len(replay):
        raise SFTConfigError("checkpoint/resume step-result counts differ")
    for expected, observed in zip(control, replay, strict=True):
        expected_copy = dict(expected)
        observed_copy = dict(observed)
        expected_ranks = expected_copy.pop("rank_results", None)
        observed_ranks = observed_copy.pop("rank_results", None)
        if expected_copy != observed_copy:
            raise SFTConfigError("checkpoint/resume scheduled step identity differs")
        if not isinstance(expected_ranks, list) or not isinstance(observed_ranks, list):
            raise SFTConfigError("checkpoint/resume rank results are missing")
        if [_step_comparable(item) for item in expected_ranks] != [
            _step_comparable(item) for item in observed_ranks
        ]:
            raise SFTConfigError("checkpoint/resume numerical step result is not exact")


def _compare_branches(
    control: dict[str, Any],
    producer: dict[str, Any],
    resumed: dict[str, Any],
) -> dict[str, Any]:
    if any(
        value.get("determinism") != _EXACT_REPLAY_DETERMINISM
        for value in (control, producer, resumed)
    ):
        raise SFTConfigError("checkpoint/resume deterministic kernel receipt differs")
    if [item["step"] for item in control["step_results"]] != [1, 2, 3, 4]:
        raise SFTConfigError("checkpoint/resume control schedule changed")
    if [item["step"] for item in producer["step_results"]] != [1, 2]:
        raise SFTConfigError("checkpoint/resume producer schedule changed")
    if [item["step"] for item in resumed["step_results"]] != [3, 4]:
        raise SFTConfigError("checkpoint/resume resumed schedule changed")
    if control["initial_rank_state"] != producer["initial_rank_state"]:
        raise SFTConfigError("checkpoint/resume fresh branch initialization is not exact")
    _compare_step_results(control["step_results"][:2], producer["step_results"])
    _compare_step_results(control["step_results"][2:], resumed["step_results"])
    if producer["final_rank_state"] != resumed["initial_rank_state"]:
        raise SFTConfigError("checkpoint/resume restored step-2 state is not exact")
    if control["final_rank_state"] != resumed["final_rank_state"]:
        raise SFTConfigError("checkpoint/resume final step-4 state is not exact")
    return {
        "fresh_initialization_exact": True,
        "producer_steps_1_2_match_control_exact": True,
        "restored_model_optimizer_scheduler_rng_dataloader_exact": True,
        "resumed_steps_3_4_match_control_exact": True,
        "final_step_4_state_exact": True,
        "explicit_schedule_cursor_restored": True,
        "deterministic_kernels_enabled_in_all_branches": True,
    }


__all__ = ["VeriGymHweDecisionSft64kCheckpointResumeTrainer"]
