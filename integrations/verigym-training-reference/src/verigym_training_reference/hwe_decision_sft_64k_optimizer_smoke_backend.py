"""Authorized dispatcher for the sealed eight-step HWE optimizer smoke."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf  # type: ignore[import-not-found]
from rllm.trainer.sft.backend import SFTConfigError  # type: ignore[import-not-found]
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    OptimizerSmokeExecutionAuthorization,
)
from verigym.schemas.hwe_training import (
    HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
    HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerSmokePreregistration,
)

from .hwe_decision_sft_64k_backend import (
    VeriGymHweDecisionSft64kBackend,
    VeriGymHweDecisionSft64kTrainer,
    assert_qualification_config,
)
from .hwe_decision_sft_64k_optimizer_smoke import (
    assert_authorized_optimizer_diagnostic_replay_config,
    assert_authorized_optimizer_smoke_config,
    optimizer_diagnostic_execution_identity,
    prepare_authorized_optimizer_diagnostic_replay_config,
    prepare_authorized_optimizer_smoke_config,
    summarize_post_step_failure_diagnostics,
)


class VeriGymHweDecisionSft64kOptimizerSmokeTrainer:
    """Prepare the exact loader and launch one authorization-bound torchrun."""

    def __init__(
        self,
        *,
        preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
        authorization: OptimizerSmokeExecutionAuthorization,
        dataset_root: Path,
        model_root: Path,
        scratch_root: Path,
    ) -> None:
        self.preregistration = preregistration
        self.authorization = authorization
        self.dispatcher = VeriGymHweDecisionSft64kTrainer(
            dataset_root=dataset_root,
            model_root=model_root,
            scratch_root=scratch_root,
            offload=False,
        )

    def prepare(self) -> VeriGymHweDecisionSft64kBackend:
        backend = self.dispatcher.prepare()
        plain = OmegaConf.to_container(backend.config, resolve=True)
        if isinstance(
            self.authorization,
            HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
        ):
            resolved = prepare_authorized_optimizer_diagnostic_replay_config(
                plain,
                self.preregistration,
                self.authorization,
            )
        else:
            resolved = prepare_authorized_optimizer_smoke_config(
                plain,
                self.preregistration,
                self.authorization,
            )
        backend._config = OmegaConf.create(resolved)
        assert_qualification_config(backend.config, offload=False)
        if isinstance(
            self.authorization,
            HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
        ):
            assert_authorized_optimizer_diagnostic_replay_config(
                backend.config,
                preregistration=self.preregistration,
                authorization=self.authorization,
            )
        else:
            assert_authorized_optimizer_smoke_config(
                backend.config,
                preregistration=self.preregistration,
                authorization=self.authorization,
            )
        return backend

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
        backend = self.prepare()
        config_path = backend.serialize_config()
        scratch = Path(backend.workdir).parent
        command = [
            sys.executable,
            "-m",
            "torch.distributed.run",
            "--standalone",
            "--nnodes=1",
            "--nproc_per_node=4",
            "-m",
            "verigym_training_reference.hwe_decision_sft_64k_optimizer_smoke_entry",
            "--config",
            config_path,
            "--preregistration",
            str(preregistration_path),
            "--authorization",
            str(authorization_path),
            "--report",
            str(report),
            "--scratch-root",
            str(scratch),
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
            self._write_failure_report(report, scratch=scratch, returncode=result.returncode)
            raise SFTConfigError(
                f"64K optimizer smoke torchrun exited with code {result.returncode}"
            )
        self._validate_pass_report(report)

    def _write_failure_report(self, report: Path, *, scratch: Path, returncode: int) -> None:
        if report.exists() or report.is_symlink():
            return
        rank_failures: list[dict[str, Any]] = []
        for rank in range(self.preregistration.profile.world_size):
            failure_path = scratch / f"rank-{rank}" / "failure.json"
            if not failure_path.is_file() or failure_path.is_symlink():
                continue
            value = json.loads(failure_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                rank_failures.append(value)
        first_error = (
            rank_failures[0]
            if rank_failures
            else {
                "error_type": "TorchrunProcessError",
                "error_message": f"torchrun exited with code {returncode}",
            }
        )
        observed_steps = [int(item.get("optimizer_steps_observed", 0)) for item in rank_failures]
        diagnostic_summary = summarize_post_step_failure_diagnostics(
            rank_failures,
            world_size=self.preregistration.profile.world_size,
        )
        is_diagnostic = isinstance(
            self.authorization,
            HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
        )
        if isinstance(
            self.authorization,
            HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
        ):
            diagnostic_format_id, diagnostic_scope = optimizer_diagnostic_execution_identity(
                self.authorization
            )
        else:
            diagnostic_format_id, diagnostic_scope = "", ""
        atomic_dump_json(
            report,
            {
                "schema_version": "1.0",
                "format_id": (
                    diagnostic_format_id
                    if is_diagnostic
                    else "verigym_hwe_decision_sft_64k_optimizer_smoke_execution_v1"
                ),
                "status": "failed_closed",
                "scope": (
                    diagnostic_scope
                    if is_diagnostic
                    else "development_optimizer_numerical_smoke_only"
                ),
                "diagnostic_replay": is_diagnostic,
                "diagnostic_replay_passed": False,
                "bf16_tolerance_replay": isinstance(
                    self.authorization,
                    (
                        HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
                        HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
                    ),
                ),
                "gradient_clip_target": getattr(
                    self.authorization,
                    "gradient_clip_target",
                    self.preregistration.acceptance.post_clip_global_norm_lte,
                ),
                "post_clip_global_norm_relative_tolerance": getattr(
                    self.authorization,
                    "post_clip_global_norm_relative_tolerance",
                    0.0,
                ),
                "post_clip_global_norm_acceptance_lte": getattr(
                    self.authorization,
                    "post_clip_global_norm_acceptance_lte",
                    self.preregistration.acceptance.post_clip_global_norm_lte,
                ),
                "optimizer_steps_authorized": self.authorization.optimizer_steps_authorized,
                "preregistration_hash": self.preregistration.preregistration_hash,
                "authorization_hash": self.authorization.authorization_hash,
                "authorization_format_id": self.authorization.format_id,
                "authorization_attempt": getattr(self.authorization, "attempt", 1),
                "replaces_authorization_hash": getattr(
                    self.authorization,
                    "replaces_authorization_hash",
                    None,
                ),
                "source_v4_dataset_hash": self.preregistration.source_v4_dataset_hash,
                "schedule_hash": self.preregistration.schedule_hash,
                "training_started": any(value > 0 for value in observed_steps),
                "optimizer_steps_observed_min": min(observed_steps, default=0),
                "optimizer_steps_observed_max": max(observed_steps, default=0),
                "optimizer_steps_confirmed_exact": len(observed_steps) == 4
                and len(set(observed_steps)) == 1,
                "checkpoint_written": False,
                "adapter_written": False,
                "development_training_ready": False,
                "production_training_ready": False,
                "new_hpc_jobs_submitted": False,
                "allocation_released": False,
                "existing_lsf_job_id": self.preregistration.existing_lsf_job_id,
                "host": self.preregistration.planned_host,
                "selected_gpu_indices": list(self.preregistration.selected_gpu_indices),
                "torchrun_returncode": returncode,
                "first_error": first_error,
                "rank_failures": rank_failures,
                **diagnostic_summary,
                "peak_memory_allocated_bytes": max(
                    (int(item.get("peak_memory_allocated_bytes", 0)) for item in rank_failures),
                    default=0,
                ),
                "peak_memory_reserved_bytes": max(
                    (int(item.get("peak_memory_reserved_bytes", 0)) for item in rank_failures),
                    default=0,
                ),
                "benchmark_score_claimed": False,
            },
        )

    def _validate_pass_report(self, report: Path) -> None:
        if not report.is_file() or report.is_symlink():
            raise SFTConfigError("64K optimizer smoke did not write a safe execution report")
        value = json.loads(report.read_text(encoding="utf-8"))
        expected: dict[str, Any] = {
            "status": "passed",
            "preregistration_hash": self.preregistration.preregistration_hash,
            "authorization_hash": self.authorization.authorization_hash,
            "loader_rows_validated": 83,
            "exact_receipts_revalidated": 83,
            "optimizer_steps": self.authorization.optimizer_steps_authorized,
            "trainable_parameter_hash_changed": True,
            "checkpoint_written": False,
            "adapter_written": False,
            "production_training_ready": False,
            "new_hpc_jobs_submitted": False,
            "allocation_released": False,
        }
        if isinstance(
            self.authorization,
            HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
        ):
            diagnostic_format_id, diagnostic_scope = optimizer_diagnostic_execution_identity(
                self.authorization
            )
            expected.update(
                {
                    "format_id": diagnostic_format_id,
                    "scope": diagnostic_scope,
                    "diagnostic_replay": True,
                    "diagnostic_replay_passed": True,
                    "development_training_ready": False,
                }
            )
        if isinstance(
            self.authorization,
            (
                HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
                HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
            ),
        ):
            expected.update(
                {
                    "bf16_tolerance_replay": True,
                    "gradient_clip_target": 1.0,
                    "post_clip_global_norm_relative_tolerance": 0.015625,
                    "post_clip_global_norm_acceptance_lte": 1.015625,
                }
            )
        if not isinstance(value, dict) or any(
            value.get(key) != item for key, item in expected.items()
        ):
            raise SFTConfigError("64K optimizer smoke pass report failed its acceptance contract")


__all__ = ["VeriGymHweDecisionSft64kOptimizerSmokeTrainer"]
