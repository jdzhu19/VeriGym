from __future__ import annotations

from pathlib import Path

import pytest
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_development_training import (
    load_development_training_preregistration,
)
from verigym.schemas.hwe_training import (
    HweDecisionSft64kDevelopmentTrainingExecutionAuthorization,
)

from verigym_training_reference.hwe_decision_sft_64k_development_canary_entry import (
    checkpoint_manifest,
    verify_checkpoint_manifest,
)
from verigym_training_reference.hwe_decision_sft_64k_development_training import (
    assert_development_canary_branch_config,
    prepare_development_canary_branch_config,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = (
    _REPOSITORY_ROOT / "configs/training/qwen35_hwe_deepseek_harness_development_training_v1.json"
)


def _authorization() -> HweDecisionSft64kDevelopmentTrainingExecutionAuthorization:
    recipe = load_development_training_preregistration(_CONFIG)
    paths = ["a.py", "b.py", "c.py", "d.py"]
    artifacts = [
        {"path": path, "size_bytes": 1, "sha256": f"{index + 1:064x}"}
        for index, path in enumerate(paths)
    ]
    base = {
        "schema_version": "1.0",
        "format_id": (
            "verigym_hwe_decision_sft_64k_development_training_execution_authorization_v1"
        ),
        "status": "authorized_for_single_32_step_canary",
        "authorization_basis": "explicit_user_instruction_authorize_32_step_canary",
        "authorization_scope": "single_preregistered_32_step_checkpoint_resume_canary",
        "recipe_hash": recipe.recipe_hash,
        "preregistration_config_sha256": "1" * 64,
        "preregistration_receipt_hash": "2" * 64,
        "preregistration_receipt_sha256": "3" * 64,
        "source_v4_dataset_hash": recipe.source_v4_dataset_hash,
        "model_identity_hash": recipe.model.model_identity_hash,
        "source_identity_hash": recipe.sources.source_identity_hash,
        "split_hash": recipe.split.split_hash,
        "schedule_hash": recipe.canary.schedule_hash,
        "execution_source_artifacts": artifacts,
        "execution_source_manifest_hash": content_hash(artifacts),
        "optimizer_steps_authorized": 32,
        "producer_optimizer_steps": 16,
        "resumed_optimizer_steps": 16,
        "checkpoint_allowed": True,
        "checkpoint_global_step": 16,
        "checkpoint_count_allowed": 1,
        "checkpoint_save_contents": ["model", "optimizer", "extra"],
        "checkpoint_load_contents": ["model", "optimizer", "extra"],
        "heldout_evaluation_steps": [0, 16, 32],
        "heldout_evaluation_record_count": 21,
        "heldout_evaluation_forward_only": True,
        "gradient_clip_target": 1.0,
        "post_clip_global_norm_relative_tolerance": 0.015625,
        "post_clip_global_norm_acceptance_lte": 1.015625,
        "tolerance_basis": "qualified_two_bfloat16_eps_relative_rounding_margin",
        "temporary_checkpoint_deletion_required": True,
        "adapter_allowed": False,
        "offload_fallback_allowed": False,
        "new_hpc_jobs_allowed": False,
        "release_existing_allocation": False,
        "existing_lsf_job_id": "466876",
        "planned_host": "gpu03",
        "selected_gpu_indices": [0, 1, 2, 3],
        "production_training_ready": False,
    }
    return HweDecisionSft64kDevelopmentTrainingExecutionAuthorization.model_validate(
        {**base, "authorization_hash": content_hash(base)}
    )


def test_development_canary_configs_freeze_step_budget_checkpoint_and_resume() -> None:
    recipe = load_development_training_preregistration(_CONFIG)
    authorization = _authorization()
    producer = prepare_development_canary_branch_config(
        {},
        recipe,
        authorization,
        branch="producer",
        checkpoint_root="/scratch/temporary-fsdp2-checkpoint",
    )
    resumed = prepare_development_canary_branch_config(
        {},
        recipe,
        authorization,
        branch="resume",
        checkpoint_root="/scratch/temporary-fsdp2-checkpoint",
    )

    assert producer["optim"]["total_training_steps"] == 32
    assert producer["checkpoint"]["save_contents"] == ["model", "optimizer", "extra"]
    assert producer["checkpoint"]["load_contents"] == []
    assert producer["verigym_development_training"]["start_step"] == 1
    assert producer["verigym_development_training"]["end_step"] == 16
    assert resumed["checkpoint"]["save_contents"] == []
    assert resumed["checkpoint"]["load_contents"] == ["model", "optimizer", "extra"]
    assert resumed["trainer"]["resume_from_path"].endswith("/global_step_16")
    assert resumed["verigym_development_training"]["start_step"] == 17
    assert resumed["verigym_development_training"]["end_step"] == 32

    resumed["optim"]["lr"] = 1e-3
    with pytest.raises(ValueError, match="optim.lr changed"):
        assert_development_canary_branch_config(
            resumed,
            preregistration=recipe,
            authorization=authorization,
            branch="resume",
            checkpoint_root="/scratch/temporary-fsdp2-checkpoint",
        )


def test_development_canary_checkpoint_manifest_round_trip_and_drift(tmp_path: Path) -> None:
    checkpoint_root = tmp_path / "temporary-fsdp2-checkpoint"
    step_root = checkpoint_root / "global_step_16"
    step_root.mkdir(parents=True)
    for kind in ("model", "optim", "extra_state"):
        for rank in range(4):
            (step_root / f"{kind}_world_size_4_rank_{rank}.pt").write_bytes(
                f"{kind}-{rank}".encode()
            )
    (step_root / "data_0.pt").write_bytes(b"dataloader")
    (step_root / "verigym_schedule_cursor.json").write_bytes(b"{}")

    manifest = checkpoint_manifest(checkpoint_root, global_step=16)
    verify_checkpoint_manifest(checkpoint_root, manifest, global_step=16)
    assert manifest["file_count"] == 14

    (step_root / "data_0.pt").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="file identity changed"):
        verify_checkpoint_manifest(checkpoint_root, manifest, global_step=16)
