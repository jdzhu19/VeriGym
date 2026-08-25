"""Coordinator for training, exporting, and independently reloading the 32-step LoRA."""

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
from verigym.hwe.deepseek_harness_adapter_canary import (
    HweDecisionSft64kAdapterCanaryAuthorization,
)
from verigym.schemas.hwe_training import HweDecisionSft64kDevelopmentTrainingPreregistration

from .hwe_decision_sft_64k_adapter_canary_entry import model_checkpoint_manifest
from .hwe_decision_sft_64k_adapter_canary_training import (
    prepare_adapter_canary_branch_config,
)
from .hwe_decision_sft_64k_backend import (
    VeriGymHweDecisionSft64kTrainer,
    assert_qualification_config,
)
from .hwe_decision_sft_64k_checkpoint_resume_entry import _delete_temporary_checkpoint
from .hwe_decision_sft_64k_development_canary_entry import verify_checkpoint_manifest
from .multiturn_sft_training import _export_adapter_checkpoint, _validate_adapter_checkpoint


class VeriGymHweDecisionSft64kAdapterCanaryTrainer:
    """Run the bounded successor canary without mutating the validated v1 artifacts."""

    def __init__(
        self,
        *,
        preregistration: HweDecisionSft64kDevelopmentTrainingPreregistration,
        authorization: HweDecisionSft64kAdapterCanaryAuthorization,
        dataset_root: Path,
        model_root: Path,
        scratch_root: Path,
        checkpoint_root: Path,
        evidence_root: Path,
        output_root: Path,
    ) -> None:
        self.preregistration = preregistration
        self.authorization = authorization
        self.dataset_root = dataset_root
        self.model_root = model_root
        self.scratch_root = scratch_root
        self.checkpoint_root = checkpoint_root
        self.evidence_root = evidence_root
        self.output_root = output_root
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
        """Train twice, export compact LoRA, reload it, and remove sharded checkpoints."""

        for output in (
            self.checkpoint_root,
            self.evidence_root,
            report,
            self.output_root / "lora_adapter",
        ):
            if output.exists() or output.is_symlink():
                raise SFTConfigError("adapter canary output already exists")
        self.evidence_root.mkdir(parents=True, mode=0o700)
        self.scratch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        backend = self.dispatcher.prepare()
        plain = OmegaConf.to_container(backend.config, resolve=True)
        if not isinstance(plain, dict):
            raise SFTConfigError("adapter canary config is not a mapping")
        assert_qualification_config(backend.config, offload=False)

        started = time.monotonic()
        branch_reports: dict[str, Path] = {}
        checkpoint_deleted = False
        try:
            for branch in ("producer", "resume"):
                branch_report = self.evidence_root / f"{branch}-branch-report.json"
                branch_reports[branch] = branch_report
                branch_scratch = self.scratch_root / branch
                branch_scratch.mkdir(parents=True, mode=0o700)
                resolved = prepare_adapter_canary_branch_config(
                    plain,
                    self.preregistration,
                    self.authorization,
                    branch=branch,
                    checkpoint_root=str(self.checkpoint_root),
                )
                config_path = branch_scratch / "resolved-config.yaml"
                OmegaConf.save(OmegaConf.create(resolved), config_path)
                self._launch_branch(
                    branch=branch,
                    config_path=config_path,
                    preregistration_path=preregistration_path,
                    authorization_path=authorization_path,
                    branch_report=branch_report,
                    branch_scratch=branch_scratch,
                    rllm_source=rllm_source,
                    verl_source=verl_source,
                    transformers_source=transformers_source,
                )
                value = _read_report(branch_report)
                if branch == "producer":
                    verify_checkpoint_manifest(
                        self.checkpoint_root,
                        value["checkpoint_manifest"],
                        global_step=16,
                    )

            producer = _read_report(branch_reports["producer"])
            resumed = _read_report(branch_reports["resume"])
            if producer["final_rank_state"] != resumed["initial_rank_state"]:
                raise SFTConfigError("adapter canary fresh-resume state is not exact")
            if [item["step"] for item in producer["step_results"]] != list(range(1, 17)):
                raise SFTConfigError("adapter canary producer schedule changed")
            if [item["step"] for item in resumed["step_results"]] != list(range(17, 33)):
                raise SFTConfigError("adapter canary resume schedule changed")
            final_checkpoint = self.checkpoint_root / "global_step_32"
            observed_final_manifest = model_checkpoint_manifest(
                self.checkpoint_root,
                global_step=32,
            )
            if observed_final_manifest != resumed["checkpoint_manifest"]:
                raise SFTConfigError("adapter canary final checkpoint identity changed")

            adapter = _export_adapter_checkpoint(final_checkpoint, destination=self.output_root)
            _validate_adapter_checkpoint(adapter)
            inference_report = self.evidence_root / "native-inference-smoke.json"
            self._launch_native_inference(adapter=adapter, report=inference_report)
            inference = _read_report(inference_report)
            if (
                inference.get("status") != "passed"
                or inference.get("independent_reload_passed") is not True
                or inference.get("native_tool_call_smoke_passed") is not True
            ):
                raise SFTConfigError("adapter canary native inference acceptance failed")
            checkpoint_deleted = _delete_temporary_checkpoint(self.checkpoint_root)
            branch_values = (producer, resumed)
            execution_wall = time.monotonic() - started
            base = {
                "schema_version": "1.0",
                "format_id": "verigym_hwe_adapter_retention_and_native_inference_canary_v1",
                "status": "passed",
                "authorization_hash": self.authorization.authorization_hash,
                "recipe_hash": self.preregistration.recipe_hash,
                "source_v4_dataset_hash": self.preregistration.source_v4_dataset_hash,
                "model_identity_hash": self.preregistration.model.model_identity_hash,
                "split_hash": self.preregistration.split.split_hash,
                "schedule_hash": self.preregistration.canary.schedule_hash,
                "optimizer_steps": 32,
                "producer_optimizer_steps": 16,
                "resumed_optimizer_steps": 16,
                "fresh_resume_exact": True,
                "loader_rows_validated_per_branch": 83,
                "exact_receipts_revalidated_per_branch": 83,
                "checkpoint_steps_written": [16, 32],
                "step_32_checkpoint_contents": ["model"],
                "temporary_checkpoints_retained": False,
                "temporary_checkpoints_deleted_after_export": checkpoint_deleted,
                "adapter_written": True,
                "adapter_path": adapter.relative_to(self.output_root).as_posix(),
                "adapter_artifact_hash": inference["adapter_artifact_hash"],
                "independent_reload_passed": True,
                "native_tool_call_smoke_passed": True,
                "native_inference_report_sha256": hashlib.sha256(
                    inference_report.read_bytes()
                ).hexdigest(),
                "heldout_base_adapter_k1_started": False,
                "heldout_base_adapter_k1_status": "separate_fail_closed_stage_pending",
                "training_started": True,
                "production_training_ready": False,
                "benchmark_score_claimed": False,
                "offload_used": False,
                "truncation_used": False,
                "world_size": 4,
                "ulysses_sequence_parallel_size": 4,
                "selected_gpu_indices": [0, 1, 2, 3],
                "existing_lsf_job_id": "466876",
                "host": "gpu03",
                "new_hpc_jobs_submitted": False,
                "allocation_released": False,
                "peak_memory_allocated_bytes": max(
                    int(value["peak_memory_allocated_bytes"]) for value in branch_values
                ),
                "peak_memory_reserved_bytes": max(
                    int(value["peak_memory_reserved_bytes"]) for value in branch_values
                ),
                "training_branch_wall_seconds": sum(
                    float(value["execution_wall_seconds"]) for value in branch_values
                ),
                "execution_wall_seconds": execution_wall,
                "gpu_seconds": sum(
                    float(value["execution_wall_seconds"]) * 4 for value in branch_values
                )
                + float(inference["wall_seconds"]),
            }
            atomic_dump_json(report, {**base, "report_hash": _content_hash(base)})
        except BaseException as error:
            if self.checkpoint_root.exists() and not self.checkpoint_root.is_symlink():
                checkpoint_deleted = _delete_temporary_checkpoint(self.checkpoint_root)
            if not report.exists() and not report.is_symlink():
                failure = {
                    "schema_version": "1.0",
                    "format_id": "verigym_hwe_adapter_retention_and_native_inference_canary_v1",
                    "status": "failed_closed",
                    "authorization_hash": self.authorization.authorization_hash,
                    "first_error_type": type(error).__name__,
                    "first_error_message": str(error)[:1000],
                    "temporary_checkpoints_deleted_after_failure": checkpoint_deleted,
                    "adapter_written": (self.output_root / "lora_adapter").is_dir(),
                    "heldout_base_adapter_k1_started": False,
                    "production_training_ready": False,
                    "benchmark_score_claimed": False,
                    "new_hpc_jobs_submitted": False,
                    "allocation_released": False,
                    "existing_lsf_job_id": "466876",
                }
                atomic_dump_json(report, {**failure, "report_hash": _content_hash(failure)})
            raise

    def _launch_branch(
        self,
        *,
        branch: str,
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
            "verigym_training_reference.hwe_decision_sft_64k_adapter_canary_entry",
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
        environment.pop("ROCR_VISIBLE_DEVICES", None)
        result = subprocess.run(command, env=environment, check=False)
        if result.returncode != 0:
            raise SFTConfigError(f"adapter canary {branch} exited with {result.returncode}")
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
        if any(value.get(key) != expected_value for key, expected_value in expected.items()):
            raise SFTConfigError(f"adapter canary {branch} report failed acceptance")

    def _launch_native_inference(self, *, adapter: Path, report: Path) -> None:
        command = [
            sys.executable,
            "-m",
            "verigym_training_reference.hwe_decision_sft_64k_native_inference",
            "--model-root",
            str(self.model_root),
            "--adapter",
            str(adapter),
            "--dataset-root",
            str(self.dataset_root),
            "--report",
            str(report),
        ]
        environment = {**os.environ, "CUDA_VISIBLE_DEVICES": "0"}
        environment.pop("ROCR_VISIBLE_DEVICES", None)
        result = subprocess.run(command, env=environment, check=False)
        if result.returncode != 0:
            raise SFTConfigError(f"adapter native inference exited with {result.returncode}")


def _read_report(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SFTConfigError("adapter canary report is not a safe regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SFTConfigError("adapter canary report is not an object")
    return value


def _content_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = ["VeriGymHweDecisionSft64kAdapterCanaryTrainer"]
