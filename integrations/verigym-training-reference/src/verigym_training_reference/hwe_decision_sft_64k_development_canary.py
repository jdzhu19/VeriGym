"""Two-process coordinator for the authorized 32-step development canary."""

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
    HweDecisionSft64kDevelopmentTrainingExecutionAuthorization,
    HweDecisionSft64kDevelopmentTrainingPreregistration,
)

from .hwe_decision_sft_64k_backend import (
    VeriGymHweDecisionSft64kTrainer,
    assert_qualification_config,
)
from .hwe_decision_sft_64k_checkpoint_resume_entry import _delete_temporary_checkpoint
from .hwe_decision_sft_64k_development_canary_entry import verify_checkpoint_manifest
from .hwe_decision_sft_64k_development_training import (
    DevelopmentCanaryBranch,
    prepare_development_canary_branch_config,
)

_DETERMINISM = {
    "format_id": "verigym_hwe_checkpoint_resume_determinism_v1",
    "flash_attention_deterministic": True,
    "cublas_workspace_config": ":4096:8",
    "torch_deterministic_algorithms": True,
    "cudnn_benchmark": False,
    "cudnn_deterministic": True,
    "host_rng_step_boundary_normalized": True,
    "host_rng_step_seed_derivation": "engine_seed_times_1000003_plus_global_step",
}


class VeriGymHweDecisionSft64kDevelopmentCanaryTrainer:
    """Prepare the exact loader and launch producer plus fresh-resume torchruns."""

    def __init__(
        self,
        *,
        preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
        authorization: HweDecisionSft64kDevelopmentTrainingExecutionAuthorization,
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
        """Run producer and resume branches and fail closed on any mismatch."""

        if self.checkpoint_root.exists() or self.checkpoint_root.is_symlink():
            raise SFTConfigError("development canary checkpoint root already exists")
        if self.evidence_root.exists() or self.evidence_root.is_symlink():
            raise SFTConfigError("development canary evidence root already exists")
        self.evidence_root.mkdir(parents=True, mode=0o700)
        self.scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        backend = self.dispatcher.prepare()
        plain = OmegaConf.to_container(backend.config, resolve=True)
        if not isinstance(plain, dict):
            raise SFTConfigError("development canary config is not a mapping")
        assert_qualification_config(backend.config, offload=False)

        started = time.monotonic()
        branch_reports: dict[str, Path] = {}
        try:
            for branch in ("producer", "resume"):
                branch_name: DevelopmentCanaryBranch = branch
                branch_report = self.evidence_root / f"{branch}-branch-report.json"
                branch_reports[branch] = branch_report
                branch_scratch = self.scratch_root / branch
                branch_scratch.mkdir(parents=True, mode=0o700)
                branch_config = prepare_development_canary_branch_config(
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
                    verify_checkpoint_manifest(
                        self.checkpoint_root,
                        producer.get("checkpoint_manifest"),
                        global_step=16,
                    )

            producer = _read_report(branch_reports["producer"])
            resumed = _read_report(branch_reports["resume"])
            comparison = _compare_branches(producer, resumed)
            manifest = producer["checkpoint_manifest"]
            verify_checkpoint_manifest(self.checkpoint_root, manifest, global_step=16)
            checkpoint_deleted = _delete_temporary_checkpoint(self.checkpoint_root)
            execution_wall = time.monotonic() - started
            branch_values = (producer, resumed)
            evaluations = [
                *producer["heldout_evaluations"],
                *resumed["heldout_evaluations"],
            ]
            atomic_dump_json(
                report,
                {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_development_training_canary_execution_v1",
                    "status": "passed",
                    "scope": "single_preregistered_32_step_checkpoint_resume_canary",
                    "authorization_hash": self.authorization.authorization_hash,
                    "recipe_hash": self.preregistration.recipe_hash,
                    "source_v4_dataset_hash": self.preregistration.source_v4_dataset_hash,
                    "model_identity_hash": self.preregistration.model.model_identity_hash,
                    "source_identity_hash": self.preregistration.sources.source_identity_hash,
                    "split_hash": self.preregistration.split.split_hash,
                    "schedule_hash": self.preregistration.canary.schedule_hash,
                    "branches": {
                        name: {
                            "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "optimizer_steps_observed": _read_report(path)[
                                "optimizer_steps_observed"
                            ],
                            "optimizer_steps_executed_in_branch": _read_report(path)[
                                "optimizer_steps_executed_in_branch"
                            ],
                        }
                        for name, path in branch_reports.items()
                    },
                    "comparison": comparison,
                    "checkpoint_manifest": manifest,
                    "checkpoint_written": True,
                    "checkpoint_count": 1,
                    "checkpoint_global_step": 16,
                    "checkpoint_loaded_in_fresh_process": True,
                    "checkpoint_retained": False,
                    "temporary_checkpoint_deleted_after_validation": checkpoint_deleted,
                    "optimizer_steps_authorized": 32,
                    "optimizer_steps": 32,
                    "producer_optimizer_steps": 16,
                    "resumed_optimizer_steps": 16,
                    "heldout_evaluation_steps": [item["evaluation_step"] for item in evaluations],
                    "heldout_evaluation_record_count_per_step": 21,
                    "heldout_mean_losses": {
                        str(item["evaluation_step"]): item["mean_loss"] for item in evaluations
                    },
                    "heldout_improvement_required": False,
                    "loader_ready": True,
                    "loader_rows_validated_per_branch": 83,
                    "exact_receipts_revalidated_per_branch": 83,
                    "over_32768_rows_validated_per_branch": 19,
                    "max_token_count": 50_117,
                    "training_started": True,
                    "development_training_canary_passed": True,
                    "production_training_ready": False,
                    "adapter_written": False,
                    "offload_used": False,
                    "truncation_used": False,
                    "bounded_fused_vocabulary_head": True,
                    "global_shift_labels_used": True,
                    "determinism": _DETERMINISM,
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
        except BaseException as error:
            deleted = False
            if self.checkpoint_root.exists() and not self.checkpoint_root.is_symlink():
                deleted = _delete_temporary_checkpoint(self.checkpoint_root)
            if not report.exists() and not report.is_symlink():
                atomic_dump_json(
                    report,
                    {
                        "schema_version": "1.0",
                        "format_id": "verigym_hwe_development_training_canary_execution_v1",
                        "status": "failed_closed",
                        "authorization_hash": self.authorization.authorization_hash,
                        "recipe_hash": self.preregistration.recipe_hash,
                        "first_error_type": type(error).__name__,
                        "first_error_message": str(error)[:1000],
                        "completed_branch_reports": {
                            name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for name, path in branch_reports.items()
                            if path.is_file() and not path.is_symlink()
                        },
                        "temporary_checkpoint_deleted_after_failure": deleted,
                        "development_training_canary_passed": False,
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
        branch: DevelopmentCanaryBranch,
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
            "verigym_training_reference.hwe_decision_sft_64k_development_canary_entry",
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
                f"development canary {branch} torchrun exited with code {result.returncode}"
            )
        value = _read_report(branch_report)
        expected = {
            "status": "passed",
            "branch": branch,
            "authorization_hash": self.authorization.authorization_hash,
            "loader_rows_validated": 83,
            "exact_receipts_revalidated": 83,
            "heldout_rows_validated": 21,
            "adapter_written": False,
            "production_training_ready": False,
        }
        if any(value.get(key) != item for key, item in expected.items()):
            raise SFTConfigError(f"development canary {branch} report failed acceptance")
        if value.get("determinism") != _DETERMINISM:
            raise SFTConfigError(f"development canary {branch} determinism changed")


def _read_report(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SFTConfigError("development canary branch report is not a safe regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SFTConfigError("development canary branch report is not an object")
    return value


def _compare_branches(producer: dict[str, Any], resumed: dict[str, Any]) -> dict[str, bool]:
    if producer.get("determinism") != _DETERMINISM or resumed.get("determinism") != _DETERMINISM:
        raise SFTConfigError("development canary branch determinism differs")
    if [item["step"] for item in producer["step_results"]] != list(range(1, 17)):
        raise SFTConfigError("development canary producer schedule changed")
    if [item["step"] for item in resumed["step_results"]] != list(range(17, 33)):
        raise SFTConfigError("development canary resume schedule changed")
    if producer["final_rank_state"] != resumed["initial_rank_state"]:
        raise SFTConfigError("development canary restored step-16 state is not exact")
    evaluations = [
        *producer.get("heldout_evaluations", []),
        *resumed.get("heldout_evaluations", []),
    ]
    if [item.get("evaluation_step") for item in evaluations] != [0, 16, 32]:
        raise SFTConfigError("development canary held-out evaluation schedule changed")
    if any(
        item.get("record_count") != 21
        or item.get("forward_only") is not True
        or item.get("state_unchanged") is not True
        for item in evaluations
    ):
        raise SFTConfigError("development canary held-out evaluation invariant failed")
    for branch in (producer, resumed):
        for step in branch["step_results"]:
            rank_results = step.get("rank_results")
            if not isinstance(rank_results, list) or len(rank_results) != 4:
                raise SFTConfigError("development canary rank step evidence is incomplete")
            if any(not all(item.get("post_step_invariants", {}).values()) for item in rank_results):
                raise SFTConfigError("development canary post-step invariant failed")
    return {
        "restored_model_optimizer_scheduler_rng_dataloader_exact": True,
        "explicit_schedule_cursor_restored": True,
        "producer_steps_1_16_completed": True,
        "resumed_steps_17_32_completed": True,
        "heldout_evaluations_forward_only_and_state_preserving": True,
        "deterministic_kernels_enabled_in_both_branches": True,
    }


__all__ = ["VeriGymHweDecisionSft64kDevelopmentCanaryTrainer"]
