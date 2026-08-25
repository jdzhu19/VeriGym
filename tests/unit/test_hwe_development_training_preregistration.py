from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from verigym.hwe.deepseek_harness_development_training import (
    _validate_artifacts,
    _validate_qualification,
    load_development_training_preregistration,
)
from verigym.schemas.hwe_training import (
    HweDecisionSft64kDevelopmentTrainingPreregistration,
    HweFrozenArtifactIdentity,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = (
    _REPOSITORY_ROOT / "configs/training/qwen35_hwe_deepseek_harness_development_training_v1.json"
)


def test_development_recipe_freezes_split_schedule_checkpoint_and_no_execution() -> None:
    recipe = load_development_training_preregistration(_CONFIG)

    assert recipe.split.train_record_indices == list(range(62))
    assert recipe.split.heldout_record_indices == list(range(62, 83))
    assert recipe.split.leakage_keys == ("task_id", "sample_id", "transcript_hash")
    assert recipe.canary.schedule_indices[15] == 61
    assert recipe.canary.schedule_indices[31] == 61
    assert all(index < 62 for index in recipe.canary.schedule_indices)
    assert recipe.canary.checkpoint_global_step == 16
    assert recipe.canary.resume_in_fresh_process is True
    assert recipe.canary.heldout_evaluation_steps == (0, 16, 32)
    assert recipe.execution_authorized is False
    assert recipe.training_started is False
    assert recipe.optimizer_steps == 0
    assert recipe.adapter_written is False


def test_development_recipe_rejects_schedule_or_split_drift() -> None:
    payload = json.loads(_CONFIG.read_text(encoding="utf-8"))
    payload["canary"]["schedule_indices"][0] = 62
    with pytest.raises(ValueError, match="sample order changed"):
        HweDecisionSft64kDevelopmentTrainingPreregistration.model_validate(payload)

    payload = json.loads(_CONFIG.read_text(encoding="utf-8"))
    payload["split"]["heldout_record_indices"][0] = 61
    with pytest.raises(ValueError, match="held-out partition changed"):
        HweDecisionSft64kDevelopmentTrainingPreregistration.model_validate(payload)


def test_development_artifact_validation_rejects_content_drift_and_symlink(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"frozen")
    identity = HweFrozenArtifactIdentity(
        path="artifact.bin",
        size_bytes=6,
        sha256=hashlib.sha256(b"frozen").hexdigest(),
    )
    assert _validate_artifacts(tmp_path, [identity], label="test") == {}

    artifact.write_bytes(b"broken")
    with pytest.raises(ValueError, match="SHA-256 changed"):
        _validate_artifacts(tmp_path, [identity], label="test")

    artifact.unlink()
    target = tmp_path / "target.bin"
    target.write_bytes(b"frozen")
    artifact.symlink_to(target)
    with pytest.raises(ValueError, match="must not be a symlink"):
        _validate_artifacts(tmp_path, [identity], label="test")


def test_development_qualification_requires_exact_resume_and_clean_security() -> None:
    comparison = {
        "deterministic_kernels_enabled_in_all_branches": True,
        "fresh_initialization_exact": True,
        "restored_model_optimizer_scheduler_rng_dataloader_exact": True,
    }
    summary = {
        "status": "passed",
        "development_training_ready": True,
        "production_training_ready": False,
        "comparison": comparison,
    }
    report = {
        **summary,
        "checkpoint_resume_ready": True,
        "temporary_checkpoint_deleted_after_validation": True,
        "adapter_written": False,
    }
    security = {
        "gate": "pass",
        "hard_secret_leak_count": 0,
        "scanner_error_count": 0,
        "proxy_values_persisted_or_hashed": False,
    }
    payloads = {
        "checkpoint-resume-qualification-summary.json": json.dumps(summary).encode(),
        "execution-checkpoint-resume-report.json": json.dumps(report).encode(),
        "security-scan.json": json.dumps(security).encode(),
    }
    _validate_qualification(payloads)

    report["checkpoint_resume_ready"] = False
    payloads["execution-checkpoint-resume-report.json"] = json.dumps(report).encode()
    with pytest.raises(ValueError, match="lacks checkpoint/resume readiness"):
        _validate_qualification(payloads)
