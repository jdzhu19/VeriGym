from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.authorize_hwe_deepseek_checkpoint_resume_qualification_v1 import (
    authorize_checkpoint_resume_qualification,
)
from scripts.authorize_hwe_deepseek_optimizer_authorized_schedule_replay_v1 import (
    authorize_authorized_schedule_replay,
)
from scripts.authorize_hwe_deepseek_optimizer_bf16_tolerance_replay_v1 import (
    authorize_bf16_tolerance_replay,
)
from scripts.authorize_hwe_deepseek_optimizer_diagnostic_replay_v1 import (
    authorize_diagnostic_replay,
)
from scripts.authorize_hwe_deepseek_optimizer_full_smoke_bf16_tolerance_replay_v1 import (
    authorize_full_smoke_bf16_tolerance_replay,
)
from scripts.authorize_hwe_deepseek_optimizer_full_smoke_replay_v1 import (
    authorize_full_smoke_replay,
)
from scripts.authorize_hwe_deepseek_optimizer_smoke_retry_v1 import authorize_retry
from scripts.authorize_hwe_deepseek_optimizer_smoke_v1 import authorize
from scripts.preregister_hwe_deepseek_optimizer_smoke_v1 import preregister
from scripts.run_hwe_deepseek_checkpoint_resume_qualification_v1 import (
    _consume_authorization as _consume_checkpoint_resume_authorization,
)
from scripts.run_hwe_deepseek_optimizer_smoke_v1 import _consume_authorization
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    GPU_QUALIFICATION_SHA256,
    QUALIFICATION_SUMMARY_SHA256,
    SCHEDULE_INDICES,
    V4_MANIFEST_SHA256,
    V4_TRAIN_JSONL_SHA256,
    create_checkpoint_resume_qualification_authorization,
    create_optimizer_authorized_schedule_replay_authorization,
    create_optimizer_bf16_tolerance_replay_authorization,
    create_optimizer_diagnostic_replay_authorization,
    create_optimizer_full_smoke_bf16_tolerance_replay_authorization,
    create_optimizer_full_smoke_replay_authorization,
    create_optimizer_smoke_execution_authorization,
    create_optimizer_smoke_execution_retry_authorization,
    load_optimizer_smoke_execution_authorization,
    load_optimizer_smoke_preregistration,
    validate_checkpoint_resume_qualification_authorization,
    validate_optimizer_authorized_schedule_replay_authorization,
    validate_optimizer_bf16_tolerance_replay_authorization,
    validate_optimizer_diagnostic_replay_authorization,
    validate_optimizer_full_smoke_bf16_tolerance_replay_authorization,
    validate_optimizer_full_smoke_replay_authorization,
    validate_optimizer_smoke_execution_authorization,
    validate_optimizer_smoke_execution_retry_authorization,
    validate_optimizer_smoke_preregistration,
)
from verigym.schemas.hwe_training import (
    HweDecisionSft64kCheckpointResumeQualificationAuthorization,
    HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization,
    HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
    HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    HweDecisionSft64kOptimizerFullSmokeReplayAuthorization,
    HweDecisionSft64kOptimizerSmokeExecutionAuthorization,
    HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization,
    HweDecisionSft64kOptimizerSmokePreregistration,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _REPOSITORY_ROOT / "configs/training/qwen35_hwe_deepseek_harness_optimizer_smoke_v1.json"
_V3_ROOT = Path(
    "/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/pilot-3task-v3/dataset"
)
_QUALIFICATION_ROOT = Path(
    "/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/decision-sft-64k-v4"
)
_PREREGISTRATION_RECEIPT = Path(
    "/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/optimizer-smoke-v1/"
    "preregistration-receipt.json"
)
_OPTIMIZER_SMOKE_ROOT = _PREREGISTRATION_RECEIPT.parent
_EXECUTION_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-authorization.json"
_FAILED_EXECUTION_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-report.json"
_RETRY_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-retry-authorization.json"
_RETRY_FAILURE_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-retry-report.json"
_DIAGNOSTIC_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-diagnostic-authorization.json"
_DIAGNOSTIC_FAILURE_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-diagnostic-report.json"
_BF16_TOLERANCE_AUTHORIZATION = (
    _OPTIMIZER_SMOKE_ROOT / "execution-bf16-tolerance-authorization.json"
)
_BF16_TOLERANCE_FAILURE_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-bf16-tolerance-report.json"
_BF16_TOLERANCE_RANK_DIAGNOSTICS = tuple(
    _OPTIMIZER_SMOKE_ROOT
    / "bf16-tolerance-rank-evidence"
    / f"rank-{rank}-step-01-post-step-diagnostics.json"
    for rank in range(4)
)
_AUTHORIZED_SCHEDULE_AUTHORIZATION = (
    _OPTIMIZER_SMOKE_ROOT / "execution-authorized-schedule-authorization.json"
)
_AUTHORIZED_SCHEDULE_PASS_REPORT = (
    _OPTIMIZER_SMOKE_ROOT / "execution-authorized-schedule-report.json"
)
_AUTHORIZED_SCHEDULE_RANK_DIAGNOSTICS = tuple(
    _OPTIMIZER_SMOKE_ROOT
    / "authorized-schedule-rank-evidence"
    / f"rank-{rank}-step-01-post-step-diagnostics.json"
    for rank in range(4)
)
_FULL_SMOKE_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-full-smoke-authorization.json"
_FULL_SMOKE_FAILURE_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-full-smoke-report.json"
_FULL_SMOKE_RANK_DIAGNOSTICS = tuple(
    _OPTIMIZER_SMOKE_ROOT
    / "full-smoke-rank-evidence"
    / f"rank-{rank}-step-{step:02d}-post-step-diagnostics.json"
    for rank in range(4)
    for step in (1, 2)
)
_ATTEMPT6_TRAINING_WHEEL = Path(
    "/data/jzhu484/Agent/datasets/wheelhouse/hwe-optimizer-full-smoke-replay-v1/"
    "verigym_training_reference-0.3.0-py3-none-any.whl"
)
_FIXED_IMPLEMENTATION_SOURCE = (
    _REPOSITORY_ROOT / "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_optimizer_smoke_entry.py"
)
_ATTEMPT_7_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-full-smoke-bf16-authorization.json"
_ATTEMPT_7_PASS_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-full-smoke-bf16-report.json"
_ATTEMPT_7_SUMMARY = _OPTIMIZER_SMOKE_ROOT / "full-smoke-bf16-replay-summary.json"
_ATTEMPT_7_RANK_DIAGNOSTICS = tuple(
    _OPTIMIZER_SMOKE_ROOT
    / "full-smoke-bf16-rank-evidence"
    / f"rank-{rank}-step-{step:02d}-post-step-diagnostics.json"
    for rank in range(4)
    for step in range(1, 9)
)
_CHECKPOINT_RESUME_IMPLEMENTATION_SOURCE = (
    _REPOSITORY_ROOT / "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_checkpoint_resume_entry.py"
)


def _qualified_artifacts_present() -> bool:
    return all(
        path.is_file()
        for path in (
            _QUALIFICATION_ROOT / "dataset/dataset-manifest.json",
            _QUALIFICATION_ROOT / "dataset/train.jsonl",
            _QUALIFICATION_ROOT / "qualification-summary.json",
            _QUALIFICATION_ROOT / "gpu-qualification-primary.json",
        )
    )


def _authorization_artifacts_present() -> bool:
    return _qualified_artifacts_present() and _PREREGISTRATION_RECEIPT.is_file()


def _retry_artifacts_present() -> bool:
    return (
        _authorization_artifacts_present()
        and _EXECUTION_AUTHORIZATION.is_file()
        and _FAILED_EXECUTION_REPORT.is_file()
    )


def _diagnostic_artifacts_present() -> bool:
    return (
        _retry_artifacts_present()
        and _RETRY_AUTHORIZATION.is_file()
        and _RETRY_FAILURE_REPORT.is_file()
    )


def _bf16_tolerance_artifacts_present() -> bool:
    return (
        _diagnostic_artifacts_present()
        and _DIAGNOSTIC_AUTHORIZATION.is_file()
        and _DIAGNOSTIC_FAILURE_REPORT.is_file()
    )


def _authorized_schedule_artifacts_present() -> bool:
    return (
        _bf16_tolerance_artifacts_present()
        and _BF16_TOLERANCE_AUTHORIZATION.is_file()
        and _BF16_TOLERANCE_FAILURE_REPORT.is_file()
        and all(path.is_file() for path in _BF16_TOLERANCE_RANK_DIAGNOSTICS)
    )


def _full_smoke_replay_artifacts_present() -> bool:
    return (
        _authorized_schedule_artifacts_present()
        and _AUTHORIZED_SCHEDULE_AUTHORIZATION.is_file()
        and _AUTHORIZED_SCHEDULE_PASS_REPORT.is_file()
        and all(path.is_file() for path in _AUTHORIZED_SCHEDULE_RANK_DIAGNOSTICS)
        and _ATTEMPT6_TRAINING_WHEEL.is_file()
    )


def _full_smoke_bf16_artifacts_present() -> bool:
    return (
        _full_smoke_replay_artifacts_present()
        and _FULL_SMOKE_AUTHORIZATION.is_file()
        and _FULL_SMOKE_FAILURE_REPORT.is_file()
        and all(path.is_file() for path in _FULL_SMOKE_RANK_DIAGNOSTICS)
    )


def _attempt_7_pass_artifacts_present() -> bool:
    return (
        _full_smoke_bf16_artifacts_present()
        and _ATTEMPT_7_AUTHORIZATION.is_file()
        and _ATTEMPT_7_PASS_REPORT.is_file()
        and _ATTEMPT_7_SUMMARY.is_file()
        and all(path.is_file() for path in _ATTEMPT_7_RANK_DIAGNOSTICS)
    )


def _historical_attempt6_source(tmp_path: Path) -> Path:
    source = tmp_path / "attempt6-entry.py"
    with zipfile.ZipFile(_ATTEMPT6_TRAINING_WHEEL) as archive:
        source.write_bytes(
            archive.read("verigym_training_reference/hwe_decision_sft_64k_optimizer_smoke_entry.py")
        )
    return source


def _create_checkpoint_resume_authorization(
    *,
    implementation_source: Path = _CHECKPOINT_RESUME_IMPLEMENTATION_SOURCE,
) -> HweDecisionSft64kCheckpointResumeQualificationAuthorization:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    return create_checkpoint_resume_qualification_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_attempt_7_authorization_path=_ATTEMPT_7_AUTHORIZATION,
        prior_attempt_7_pass_report_path=_ATTEMPT_7_PASS_REPORT,
        prior_attempt_7_summary_path=_ATTEMPT_7_SUMMARY,
        prior_attempt_7_rank_diagnostic_paths=_ATTEMPT_7_RANK_DIAGNOSTICS,
        implementation_source_path=implementation_source,
    )


def _reseal(value: dict[str, object]) -> dict[str, object]:
    value["schedule_hash"] = content_hash(value["schedule"])
    identity = {key: item for key, item in value.items() if key != "preregistration_hash"}
    value["preregistration_hash"] = content_hash(identity)
    return value


def test_optimizer_diagnostic_authorization_is_consumed_once(tmp_path: Path) -> None:
    authorization = tmp_path / "execution-diagnostic-authorization.json"
    authorization.write_text("{}", encoding="utf-8")
    marker = _consume_authorization(authorization, authorization_hash="a" * 64)

    assert marker.name == "execution-diagnostic-started.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["authorization_hash"] == "a" * 64
    assert payload["single_use_authorization_consumed"] is True
    with pytest.raises(FileExistsError):
        _consume_authorization(authorization, authorization_hash="a" * 64)


def test_optimizer_bf16_tolerance_authorization_is_consumed_once(tmp_path: Path) -> None:
    authorization = tmp_path / "execution-bf16-tolerance-authorization.json"
    authorization.write_text("{}", encoding="utf-8")
    marker = _consume_authorization(authorization, authorization_hash="b" * 64)

    assert marker.name == "execution-bf16-tolerance-started.json"
    with pytest.raises(FileExistsError):
        _consume_authorization(authorization, authorization_hash="b" * 64)


def test_optimizer_authorized_schedule_authorization_is_consumed_once(tmp_path: Path) -> None:
    authorization = tmp_path / "execution-authorized-schedule-authorization.json"
    authorization.write_text("{}", encoding="utf-8")
    marker = _consume_authorization(authorization, authorization_hash="c" * 64)

    assert marker.name == "execution-authorized-schedule-started.json"
    with pytest.raises(FileExistsError):
        _consume_authorization(authorization, authorization_hash="c" * 64)


def test_optimizer_full_smoke_authorization_is_consumed_once(tmp_path: Path) -> None:
    authorization = tmp_path / "execution-full-smoke-authorization.json"
    authorization.write_text("{}", encoding="utf-8")
    marker = _consume_authorization(authorization, authorization_hash="d" * 64)

    assert marker.name == "execution-full-smoke-started.json"
    with pytest.raises(FileExistsError):
        _consume_authorization(authorization, authorization_hash="d" * 64)


def test_optimizer_full_smoke_bf16_authorization_is_consumed_once(tmp_path: Path) -> None:
    authorization = tmp_path / "execution-full-smoke-bf16-authorization.json"
    authorization.write_text("{}", encoding="utf-8")
    marker = _consume_authorization(authorization, authorization_hash="e" * 64)

    assert marker.name == "execution-full-smoke-bf16-started.json"
    with pytest.raises(FileExistsError):
        _consume_authorization(authorization, authorization_hash="e" * 64)


def test_checkpoint_resume_authorization_is_consumed_once(tmp_path: Path) -> None:
    authorization = tmp_path / "execution-checkpoint-resume-authorization.json"
    authorization.write_text("{}", encoding="utf-8")
    marker = _consume_checkpoint_resume_authorization(authorization, "f" * 64)

    assert marker.name == "execution-checkpoint-resume-started.json"
    with pytest.raises(FileExistsError):
        _consume_checkpoint_resume_authorization(authorization, "f" * 64)


def test_optimizer_smoke_static_preregistration_is_sealed_and_not_started() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)

    assert plan.status == "preregistered_not_started"
    assert tuple(item.source_v4_record_index for item in plan.schedule) == SCHEDULE_INDICES
    assert plan.acceptance.longest_repeat_steps == (4, 8)
    assert plan.acceptance.optimizer_steps_required == 8
    assert plan.acceptance.checkpoint_allowed is False
    assert plan.acceptance.adapter_allowed is False
    assert plan.acceptance.offload_fallback_allowed is False
    assert plan.training_started is False
    assert plan.optimizer_steps == 0
    assert plan.production_training_ready is False


def test_optimizer_smoke_rejects_resealed_schedule_or_numerical_drift() -> None:
    payload = json.loads(_CONFIG.read_text(encoding="utf-8"))
    payload["schedule"][0]["source_v4_record_index"] = 0
    with pytest.raises(ValidationError, match="record order changed"):
        HweDecisionSft64kOptimizerSmokePreregistration.model_validate(_reseal(payload))

    payload = json.loads(_CONFIG.read_text(encoding="utf-8"))
    payload["optimizer"]["learning_rate"] = 0.001
    with pytest.raises(ValidationError, match="numerical settings changed"):
        HweDecisionSft64kOptimizerSmokePreregistration.model_validate(_reseal(payload))


@pytest.mark.skipif(
    not _qualified_artifacts_present(),
    reason="qualified local DeepSeek Harness artifacts are not installed",
)
def test_real_optimizer_smoke_receipt_binds_v4_and_zero_step_qualification() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    receipt = validate_optimizer_smoke_preregistration(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
    )

    assert receipt["status"] == "preregistered_not_started"
    assert receipt["source_v4_manifest_sha256"] == V4_MANIFEST_SHA256
    assert receipt["source_v4_train_jsonl_sha256"] == V4_TRAIN_JSONL_SHA256
    assert receipt["qualification_summary_sha256"] == QUALIFICATION_SUMMARY_SHA256
    assert receipt["gpu_qualification_sha256"] == GPU_QUALIFICATION_SHA256
    assert receipt["schedule_indices"] == list(SCHEDULE_INDICES)
    assert receipt["actual_optimizer_execution_authorized"] is False
    assert receipt["training_started"] is False
    assert receipt["optimizer_steps"] == 0
    assert receipt["checkpoint_written"] is False
    assert receipt["adapter_written"] is False
    identity = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    assert receipt["receipt_hash"] == content_hash(identity)


@pytest.mark.skipif(
    not _qualified_artifacts_present(),
    reason="qualified local DeepSeek Harness artifacts are not installed",
)
def test_preregistration_writer_snapshots_config_and_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "preregistration"
    receipt = preregister(
        config=_CONFIG,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        output=output,
    )

    assert (output / "preregistration-config.json").read_bytes() == _CONFIG.read_bytes()
    persisted = json.loads((output / "preregistration-receipt.json").read_text(encoding="utf-8"))
    assert persisted == receipt
    with pytest.raises(ValueError, match="must not already exist"):
        preregister(
            config=_CONFIG,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            output=output,
        )


@pytest.mark.skipif(
    not _qualified_artifacts_present(),
    reason="qualified local DeepSeek Harness artifacts are not installed",
)
def test_optimizer_smoke_rejects_changed_qualification_evidence(tmp_path: Path) -> None:
    qualification = tmp_path / "qualification"
    qualification.mkdir()
    shutil.copy2(
        _QUALIFICATION_ROOT / "qualification-summary.json",
        qualification / "qualification-summary.json",
    )
    gpu = json.loads(
        (_QUALIFICATION_ROOT / "gpu-qualification-primary.json").read_text(encoding="utf-8")
    )
    gpu["optimizer_steps"] = 1
    (qualification / "gpu-qualification-primary.json").write_text(
        json.dumps(gpu),
        encoding="utf-8",
    )
    plan = load_optimizer_smoke_preregistration(_CONFIG)

    with pytest.raises(ValueError, match="GPU qualification SHA-256 changed"):
        validate_optimizer_smoke_preregistration(
            plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=qualification,
            config_path=_CONFIG,
        )


@pytest.mark.skipif(
    not _qualified_artifacts_present(),
    reason="qualified local DeepSeek Harness artifacts are not installed",
)
def test_optimizer_smoke_rejects_changed_v4_bytes(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    shutil.copy2(
        _QUALIFICATION_ROOT / "dataset/dataset-manifest.json",
        dataset / "dataset-manifest.json",
    )
    original_train = _QUALIFICATION_ROOT / "dataset/train.jsonl"
    changed_train = dataset / "train.jsonl"
    shutil.copy2(original_train, changed_train)
    changed_train.write_bytes(changed_train.read_bytes() + b"\n")
    plan = load_optimizer_smoke_preregistration(_CONFIG)

    with pytest.raises(ValueError, match="train JSONL SHA-256 changed"):
        validate_optimizer_smoke_preregistration(
            plan,
            dataset_root=dataset,
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
        )


@pytest.mark.skipif(
    not (_V3_ROOT / "dataset-manifest.json").is_file() or not _qualified_artifacts_present(),
    reason="qualified local DeepSeek Harness artifacts are not installed",
)
def test_preregistration_validation_does_not_modify_v3_or_v4() -> None:
    paths = (
        _V3_ROOT / "dataset-manifest.json",
        _V3_ROOT / "train.jsonl",
        _QUALIFICATION_ROOT / "dataset/dataset-manifest.json",
        _QUALIFICATION_ROOT / "dataset/train.jsonl",
    )
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    validate_optimizer_smoke_preregistration(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
    )
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    v4_manifest = _QUALIFICATION_ROOT / "dataset/dataset-manifest.json"
    v4_train = _QUALIFICATION_ROOT / "dataset/train.jsonl"

    assert before == after
    assert before[v4_manifest] == V4_MANIFEST_SHA256
    assert before[v4_train] == V4_TRAIN_JSONL_SHA256


@pytest.mark.skipif(
    not _authorization_artifacts_present(),
    reason="optimizer-smoke preregistration artifacts are not installed",
)
def test_optimizer_smoke_execution_authorization_is_separate_and_hash_bound() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    authorization = create_optimizer_smoke_execution_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
    )

    assert authorization.status == "authorized_for_single_execution"
    assert authorization.execution_authorized is True
    assert authorization.optimizer_steps_authorized == 8
    assert authorization.checkpoint_allowed is False
    assert authorization.adapter_allowed is False
    assert authorization.preregistration_hash == plan.preregistration_hash
    assert authorization.schedule_hash == plan.schedule_hash
    identity = authorization.model_dump(mode="json", exclude={"authorization_hash"})
    assert authorization.authorization_hash == content_hash(identity)


@pytest.mark.skipif(
    not _authorization_artifacts_present(),
    reason="optimizer-smoke preregistration artifacts are not installed",
)
def test_optimizer_smoke_authorization_writer_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "execution-authorization.json"
    payload = authorize(
        config=_CONFIG,
        preregistration_receipt=_PREREGISTRATION_RECEIPT,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        output=output,
    )

    loaded = load_optimizer_smoke_execution_authorization(output)
    assert loaded == HweDecisionSft64kOptimizerSmokeExecutionAuthorization.model_validate(payload)
    with pytest.raises(ValueError, match="must not already exist"):
        authorize(
            config=_CONFIG,
            preregistration_receipt=_PREREGISTRATION_RECEIPT,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            output=output,
        )


@pytest.mark.skipif(
    not _authorization_artifacts_present(),
    reason="optimizer-smoke preregistration artifacts are not installed",
)
def test_optimizer_smoke_authorization_rejects_receipt_or_authorization_drift(
    tmp_path: Path,
) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    authorization = create_optimizer_smoke_execution_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
    )
    changed_receipt = tmp_path / "preregistration-receipt.json"
    receipt = json.loads(_PREREGISTRATION_RECEIPT.read_text(encoding="utf-8"))
    receipt["optimizer_steps"] = 1
    changed_receipt.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from frozen evidence"):
        validate_optimizer_smoke_execution_authorization(
            authorization,
            preregistration=plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=changed_receipt,
        )

    changed = authorization.model_dump(mode="json")
    changed["preregistration_receipt_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="authorization changed"):
        HweDecisionSft64kOptimizerSmokeExecutionAuthorization.model_validate(changed)


@pytest.mark.skipif(
    not _retry_artifacts_present(),
    reason="optimizer-smoke zero-step failure artifacts are not installed",
)
def test_optimizer_smoke_retry_binds_zero_step_failure_and_fixed_source(tmp_path: Path) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    retry = create_optimizer_smoke_execution_retry_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_authorization_path=_EXECUTION_AUTHORIZATION,
        prior_failure_report_path=_FAILED_EXECUTION_REPORT,
        implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )

    assert retry.attempt == 2
    assert retry.prior_optimizer_steps_confirmed == 0
    assert (
        retry.replaces_authorization_hash
        == load_optimizer_smoke_execution_authorization(_EXECUTION_AUTHORIZATION).authorization_hash
    )
    output = tmp_path / "execution-retry-authorization.json"
    payload = authorize_retry(
        config=_CONFIG,
        preregistration_receipt=_PREREGISTRATION_RECEIPT,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        prior_authorization=_EXECUTION_AUTHORIZATION,
        prior_failure_report=_FAILED_EXECUTION_REPORT,
        implementation_source=_FIXED_IMPLEMENTATION_SOURCE,
        output=output,
    )
    assert HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization.model_validate(
        payload
    ) == load_optimizer_smoke_execution_authorization(output)


@pytest.mark.skipif(
    not _retry_artifacts_present(),
    reason="optimizer-smoke zero-step failure artifacts are not installed",
)
def test_optimizer_smoke_retry_rejects_nonzero_or_changed_failure(tmp_path: Path) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    retry = create_optimizer_smoke_execution_retry_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_authorization_path=_EXECUTION_AUTHORIZATION,
        prior_failure_report_path=_FAILED_EXECUTION_REPORT,
        implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )
    changed_report = tmp_path / "execution-report.json"
    failure = json.loads(_FAILED_EXECUTION_REPORT.read_text(encoding="utf-8"))
    failure["optimizer_steps_observed_max"] = 1
    changed_report.write_text(json.dumps(failure), encoding="utf-8")

    with pytest.raises(ValueError, match="exact zero-step failure"):
        validate_optimizer_smoke_execution_retry_authorization(
            retry,
            preregistration=plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
            prior_authorization_path=_EXECUTION_AUTHORIZATION,
            prior_failure_report_path=changed_report,
            implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
        )


@pytest.mark.skipif(
    not _retry_artifacts_present(),
    reason="optimizer-smoke zero-step failure artifacts are not installed",
)
def test_optimizer_smoke_retry_rejects_implementation_source_drift(tmp_path: Path) -> None:
    implementation_source = tmp_path / "optimizer_smoke_entry.py"
    shutil.copy2(_FIXED_IMPLEMENTATION_SOURCE, implementation_source)
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    retry = create_optimizer_smoke_execution_retry_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_authorization_path=_EXECUTION_AUTHORIZATION,
        prior_failure_report_path=_FAILED_EXECUTION_REPORT,
        implementation_source_path=implementation_source,
    )
    implementation_source.write_bytes(implementation_source.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="differs from frozen failure evidence"):
        validate_optimizer_smoke_execution_retry_authorization(
            retry,
            preregistration=plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
            prior_authorization_path=_EXECUTION_AUTHORIZATION,
            prior_failure_report_path=_FAILED_EXECUTION_REPORT,
            implementation_source_path=implementation_source,
        )


@pytest.mark.skipif(
    not _diagnostic_artifacts_present(),
    reason="optimizer-smoke one-step retry failure artifacts are not installed",
)
def test_optimizer_diagnostic_authorization_binds_both_failures_and_one_step(
    tmp_path: Path,
) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    authorization = create_optimizer_diagnostic_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_authorization_path=_EXECUTION_AUTHORIZATION,
        prior_failure_report_path=_FAILED_EXECUTION_REPORT,
        prior_retry_authorization_path=_RETRY_AUTHORIZATION,
        prior_retry_failure_report_path=_RETRY_FAILURE_REPORT,
        instrumentation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )

    assert authorization.attempt == 3
    assert authorization.optimizer_steps_authorized == 1
    assert authorization.source_v4_record_index == 62
    assert authorization.source_v4_record_hash == plan.schedule[0].source_v4_record_hash
    assert authorization.development_training_ready is False
    output = tmp_path / "execution-diagnostic-authorization.json"
    payload = authorize_diagnostic_replay(
        config=_CONFIG,
        preregistration_receipt=_PREREGISTRATION_RECEIPT,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        prior_authorization=_EXECUTION_AUTHORIZATION,
        prior_failure_report=_FAILED_EXECUTION_REPORT,
        prior_retry_authorization=_RETRY_AUTHORIZATION,
        prior_retry_failure_report=_RETRY_FAILURE_REPORT,
        instrumentation_source=_FIXED_IMPLEMENTATION_SOURCE,
        output=output,
    )
    assert HweDecisionSft64kOptimizerDiagnosticReplayAuthorization.model_validate(
        payload
    ) == load_optimizer_smoke_execution_authorization(output)
    with pytest.raises(ValueError, match="must not already exist"):
        authorize_diagnostic_replay(
            config=_CONFIG,
            preregistration_receipt=_PREREGISTRATION_RECEIPT,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            prior_authorization=_EXECUTION_AUTHORIZATION,
            prior_failure_report=_FAILED_EXECUTION_REPORT,
            prior_retry_authorization=_RETRY_AUTHORIZATION,
            prior_retry_failure_report=_RETRY_FAILURE_REPORT,
            instrumentation_source=_FIXED_IMPLEMENTATION_SOURCE,
            output=output,
        )


@pytest.mark.skipif(
    not _diagnostic_artifacts_present(),
    reason="optimizer-smoke one-step retry failure artifacts are not installed",
)
def test_optimizer_diagnostic_authorization_rejects_report_or_source_drift(
    tmp_path: Path,
) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    authorization = create_optimizer_diagnostic_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_authorization_path=_EXECUTION_AUTHORIZATION,
        prior_failure_report_path=_FAILED_EXECUTION_REPORT,
        prior_retry_authorization_path=_RETRY_AUTHORIZATION,
        prior_retry_failure_report_path=_RETRY_FAILURE_REPORT,
        instrumentation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )
    changed_report = tmp_path / "execution-retry-report.json"
    shutil.copy2(_RETRY_FAILURE_REPORT, changed_report)
    changed_report.write_bytes(changed_report.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="retry failure report SHA-256 changed"):
        validate_optimizer_diagnostic_replay_authorization(
            authorization,
            preregistration=plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
            prior_authorization_path=_EXECUTION_AUTHORIZATION,
            prior_failure_report_path=_FAILED_EXECUTION_REPORT,
            prior_retry_authorization_path=_RETRY_AUTHORIZATION,
            prior_retry_failure_report_path=changed_report,
            instrumentation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
        )

    changed_source = tmp_path / "entry.py"
    shutil.copy2(_FIXED_IMPLEMENTATION_SOURCE, changed_source)
    authorization = create_optimizer_diagnostic_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_authorization_path=_EXECUTION_AUTHORIZATION,
        prior_failure_report_path=_FAILED_EXECUTION_REPORT,
        prior_retry_authorization_path=_RETRY_AUTHORIZATION,
        prior_retry_failure_report_path=_RETRY_FAILURE_REPORT,
        instrumentation_source_path=changed_source,
    )
    changed_source.write_bytes(changed_source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="differs from frozen evidence"):
        validate_optimizer_diagnostic_replay_authorization(
            authorization,
            preregistration=plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
            prior_authorization_path=_EXECUTION_AUTHORIZATION,
            prior_failure_report_path=_FAILED_EXECUTION_REPORT,
            prior_retry_authorization_path=_RETRY_AUTHORIZATION,
            prior_retry_failure_report_path=_RETRY_FAILURE_REPORT,
            instrumentation_source_path=changed_source,
        )


@pytest.mark.skipif(
    not _bf16_tolerance_artifacts_present(),
    reason="optimizer attempt-3 diagnostic evidence is not installed",
)
def test_optimizer_bf16_tolerance_replay_binds_failure_and_source(tmp_path: Path) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    authorization = create_optimizer_bf16_tolerance_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_diagnostic_authorization_path=_DIAGNOSTIC_AUTHORIZATION,
        prior_diagnostic_failure_report_path=_DIAGNOSTIC_FAILURE_REPORT,
        implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )

    assert authorization.attempt == 4
    assert authorization.optimizer_steps_authorized == 1
    assert authorization.gradient_clip_target == 1.0
    assert authorization.bfloat16_epsilon == 0.0078125
    assert authorization.tolerance_multiplier == 2
    assert authorization.post_clip_global_norm_relative_tolerance == 0.015625
    assert authorization.post_clip_global_norm_acceptance_lte == 1.015625
    assert authorization.tolerance_tuned_to_observed_value is False
    validate_optimizer_bf16_tolerance_replay_authorization(
        authorization,
        preregistration=plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_diagnostic_authorization_path=_DIAGNOSTIC_AUTHORIZATION,
        prior_diagnostic_failure_report_path=_DIAGNOSTIC_FAILURE_REPORT,
        implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )

    output = tmp_path / "execution-bf16-tolerance-authorization.json"
    payload = authorize_bf16_tolerance_replay(
        config=_CONFIG,
        preregistration_receipt=_PREREGISTRATION_RECEIPT,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        prior_diagnostic_authorization=_DIAGNOSTIC_AUTHORIZATION,
        prior_diagnostic_failure_report=_DIAGNOSTIC_FAILURE_REPORT,
        implementation_source=_FIXED_IMPLEMENTATION_SOURCE,
        output=output,
    )
    assert HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization.model_validate(
        payload
    ) == load_optimizer_smoke_execution_authorization(output)

    changed_report = tmp_path / "execution-diagnostic-report.json"
    shutil.copy2(_DIAGNOSTIC_FAILURE_REPORT, changed_report)
    changed_report.write_bytes(changed_report.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="failure report SHA-256 changed"):
        create_optimizer_bf16_tolerance_replay_authorization(
            plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
            prior_diagnostic_authorization_path=_DIAGNOSTIC_AUTHORIZATION,
            prior_diagnostic_failure_report_path=changed_report,
            implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
        )


@pytest.mark.skipif(
    not _authorized_schedule_artifacts_present(),
    reason="optimizer attempt-4 schedule-guard evidence is not installed",
)
def test_optimizer_authorized_schedule_replay_binds_four_rank_evidence(
    tmp_path: Path,
) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    rank_0, rank_1, rank_2, rank_3 = _BF16_TOLERANCE_RANK_DIAGNOSTICS
    authorization = create_optimizer_authorized_schedule_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_bf16_tolerance_authorization_path=_BF16_TOLERANCE_AUTHORIZATION,
        prior_bf16_tolerance_failure_report_path=_BF16_TOLERANCE_FAILURE_REPORT,
        prior_bf16_rank_diagnostic_paths=(rank_0, rank_1, rank_2, rank_3),
        implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )

    assert authorization.attempt == 5
    assert authorization.optimizer_steps_authorized == 1
    assert authorization.prior_bf16_tolerance_optimizer_steps_confirmed == 1
    assert authorization.prior_bf16_post_step_invariants_all_passed is True
    assert authorization.prior_second_optimizer_step_executed is False
    assert authorization.implementation_fix == "execution_loop_uses_authorized_schedule"
    validate_optimizer_authorized_schedule_replay_authorization(
        authorization,
        preregistration=plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_bf16_tolerance_authorization_path=_BF16_TOLERANCE_AUTHORIZATION,
        prior_bf16_tolerance_failure_report_path=_BF16_TOLERANCE_FAILURE_REPORT,
        prior_bf16_rank_diagnostic_paths=(rank_0, rank_1, rank_2, rank_3),
        implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )

    output = tmp_path / "execution-authorized-schedule-authorization.json"
    payload = authorize_authorized_schedule_replay(
        config=_CONFIG,
        preregistration_receipt=_PREREGISTRATION_RECEIPT,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        prior_bf16_tolerance_authorization=_BF16_TOLERANCE_AUTHORIZATION,
        prior_bf16_tolerance_failure_report=_BF16_TOLERANCE_FAILURE_REPORT,
        prior_bf16_rank_diagnostics=list(_BF16_TOLERANCE_RANK_DIAGNOSTICS),
        implementation_source=_FIXED_IMPLEMENTATION_SOURCE,
        output=output,
    )
    assert HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization.model_validate(
        payload
    ) == load_optimizer_smoke_execution_authorization(output)

    changed_rank = tmp_path / "rank-0-step-01-post-step-diagnostics.json"
    shutil.copy2(rank_0, changed_rank)
    changed_rank.write_bytes(changed_rank.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="rank 0 evidence changed"):
        create_optimizer_authorized_schedule_replay_authorization(
            plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
            prior_bf16_tolerance_authorization_path=_BF16_TOLERANCE_AUTHORIZATION,
            prior_bf16_tolerance_failure_report_path=_BF16_TOLERANCE_FAILURE_REPORT,
            prior_bf16_rank_diagnostic_paths=(changed_rank, rank_1, rank_2, rank_3),
            implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
        )


@pytest.mark.skipif(
    not _full_smoke_replay_artifacts_present(),
    reason="optimizer attempt-5 pass evidence is not installed",
)
def test_optimizer_full_smoke_replay_binds_attempt_five_pass(tmp_path: Path) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    rank_0, rank_1, rank_2, rank_3 = _AUTHORIZED_SCHEDULE_RANK_DIAGNOSTICS
    attempt6_source = _historical_attempt6_source(tmp_path)
    authorization = create_optimizer_full_smoke_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_authorized_schedule_authorization_path=_AUTHORIZED_SCHEDULE_AUTHORIZATION,
        prior_authorized_schedule_pass_report_path=_AUTHORIZED_SCHEDULE_PASS_REPORT,
        prior_authorized_schedule_rank_diagnostic_paths=(rank_0, rank_1, rank_2, rank_3),
        implementation_source_path=attempt6_source,
    )

    assert authorization.attempt == 6
    assert authorization.optimizer_steps_authorized == 8
    assert authorization.schedule_indices == SCHEDULE_INDICES
    assert authorization.prior_authorized_schedule_optimizer_steps_confirmed == 1
    assert authorization.prior_authorized_schedule_invariants_all_passed is True
    validate_optimizer_full_smoke_replay_authorization(
        authorization,
        preregistration=plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_authorized_schedule_authorization_path=_AUTHORIZED_SCHEDULE_AUTHORIZATION,
        prior_authorized_schedule_pass_report_path=_AUTHORIZED_SCHEDULE_PASS_REPORT,
        prior_authorized_schedule_rank_diagnostic_paths=(rank_0, rank_1, rank_2, rank_3),
        implementation_source_path=attempt6_source,
    )

    output = tmp_path / "execution-full-smoke-authorization.json"
    payload = authorize_full_smoke_replay(
        config=_CONFIG,
        preregistration_receipt=_PREREGISTRATION_RECEIPT,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        prior_authorized_schedule_authorization=_AUTHORIZED_SCHEDULE_AUTHORIZATION,
        prior_authorized_schedule_pass_report=_AUTHORIZED_SCHEDULE_PASS_REPORT,
        prior_authorized_schedule_rank_diagnostics=list(_AUTHORIZED_SCHEDULE_RANK_DIAGNOSTICS),
        implementation_source=attempt6_source,
        output=output,
    )
    assert HweDecisionSft64kOptimizerFullSmokeReplayAuthorization.model_validate(
        payload
    ) == load_optimizer_smoke_execution_authorization(output)

    changed_rank = tmp_path / "rank-0-step-01-post-step-diagnostics.json"
    shutil.copy2(rank_0, changed_rank)
    changed_rank.write_bytes(changed_rank.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="rank 0 evidence changed"):
        create_optimizer_full_smoke_replay_authorization(
            plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
            prior_authorized_schedule_authorization_path=(_AUTHORIZED_SCHEDULE_AUTHORIZATION),
            prior_authorized_schedule_pass_report_path=_AUTHORIZED_SCHEDULE_PASS_REPORT,
            prior_authorized_schedule_rank_diagnostic_paths=(
                changed_rank,
                rank_1,
                rank_2,
                rank_3,
            ),
            implementation_source_path=attempt6_source,
        )


@pytest.mark.skipif(
    not _full_smoke_bf16_artifacts_present(),
    reason="optimizer attempt-6 BF16-only failure evidence is not installed",
)
def test_optimizer_full_smoke_bf16_replay_binds_attempt_six_failure(
    tmp_path: Path,
) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    diagnostics = tuple(_FULL_SMOKE_RANK_DIAGNOSTICS)
    authorization = create_optimizer_full_smoke_bf16_tolerance_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_full_smoke_authorization_path=_FULL_SMOKE_AUTHORIZATION,
        prior_full_smoke_failure_report_path=_FULL_SMOKE_FAILURE_REPORT,
        prior_full_smoke_rank_diagnostic_paths=(
            diagnostics[0],
            diagnostics[1],
            diagnostics[2],
            diagnostics[3],
            diagnostics[4],
            diagnostics[5],
            diagnostics[6],
            diagnostics[7],
        ),
        implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )

    assert authorization.attempt == 7
    assert authorization.optimizer_steps_authorized == 8
    assert authorization.prior_full_smoke_optimizer_steps_confirmed == 2
    assert authorization.prior_full_smoke_failure_step == 2
    assert authorization.gradient_clip_target == 1.0
    assert authorization.post_clip_global_norm_relative_tolerance == 0.015625
    assert authorization.post_clip_global_norm_acceptance_lte == 1.015625
    assert authorization.tolerance_inherited_from_prior_authorized_schedule is True
    assert authorization.tolerance_tuned_to_observed_value is False
    validate_optimizer_full_smoke_bf16_tolerance_replay_authorization(
        authorization,
        preregistration=plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_full_smoke_authorization_path=_FULL_SMOKE_AUTHORIZATION,
        prior_full_smoke_failure_report_path=_FULL_SMOKE_FAILURE_REPORT,
        prior_full_smoke_rank_diagnostic_paths=(
            diagnostics[0],
            diagnostics[1],
            diagnostics[2],
            diagnostics[3],
            diagnostics[4],
            diagnostics[5],
            diagnostics[6],
            diagnostics[7],
        ),
        implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
    )

    output = tmp_path / "execution-full-smoke-bf16-authorization.json"
    payload = authorize_full_smoke_bf16_tolerance_replay(
        config=_CONFIG,
        preregistration_receipt=_PREREGISTRATION_RECEIPT,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        prior_full_smoke_authorization=_FULL_SMOKE_AUTHORIZATION,
        prior_full_smoke_failure_report=_FULL_SMOKE_FAILURE_REPORT,
        prior_full_smoke_rank_diagnostics=list(diagnostics),
        implementation_source=_FIXED_IMPLEMENTATION_SOURCE,
        output=output,
    )
    assert HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization.model_validate(
        payload
    ) == load_optimizer_smoke_execution_authorization(output)

    changed_report = tmp_path / "execution-full-smoke-report.json"
    shutil.copy2(_FULL_SMOKE_FAILURE_REPORT, changed_report)
    changed_report.write_bytes(changed_report.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="failure report changed"):
        create_optimizer_full_smoke_bf16_tolerance_replay_authorization(
            plan,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
            prior_full_smoke_authorization_path=_FULL_SMOKE_AUTHORIZATION,
            prior_full_smoke_failure_report_path=changed_report,
            prior_full_smoke_rank_diagnostic_paths=(
                diagnostics[0],
                diagnostics[1],
                diagnostics[2],
                diagnostics[3],
                diagnostics[4],
                diagnostics[5],
                diagnostics[6],
                diagnostics[7],
            ),
            implementation_source_path=_FIXED_IMPLEMENTATION_SOURCE,
        )


@pytest.mark.skipif(
    not _attempt_7_pass_artifacts_present(),
    reason="optimizer attempt-7 pass evidence is not installed",
)
def test_checkpoint_resume_authorization_binds_exact_attempt_7_pass(tmp_path: Path) -> None:
    authorization = _create_checkpoint_resume_authorization()

    assert authorization.attempt == 8
    assert authorization.replaces_authorization_hash == (
        "a2329c519edd2010aa41bde88168b7f2c24e25714dafaf81e09bbcde3e4857c8"
    )
    assert authorization.checkpoint_allowed is True
    assert authorization.control_optimizer_steps == 4
    assert authorization.checkpoint_producer_optimizer_steps == 2
    assert authorization.resumed_optimizer_steps == 2
    assert authorization.checkpoint_save_contents == ("model", "optimizer", "extra")
    assert len(authorization.prior_attempt_7_rank_diagnostic_sha256) == 32
    validate_checkpoint_resume_qualification_authorization(
        authorization,
        preregistration=load_optimizer_smoke_preregistration(_CONFIG),
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_attempt_7_authorization_path=_ATTEMPT_7_AUTHORIZATION,
        prior_attempt_7_pass_report_path=_ATTEMPT_7_PASS_REPORT,
        prior_attempt_7_summary_path=_ATTEMPT_7_SUMMARY,
        prior_attempt_7_rank_diagnostic_paths=_ATTEMPT_7_RANK_DIAGNOSTICS,
        implementation_source_path=_CHECKPOINT_RESUME_IMPLEMENTATION_SOURCE,
    )

    output = tmp_path / "execution-checkpoint-resume-authorization.json"
    payload = authorize_checkpoint_resume_qualification(
        config=_CONFIG,
        preregistration_receipt=_PREREGISTRATION_RECEIPT,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        prior_attempt_7_authorization=_ATTEMPT_7_AUTHORIZATION,
        prior_attempt_7_pass_report=_ATTEMPT_7_PASS_REPORT,
        prior_attempt_7_summary=_ATTEMPT_7_SUMMARY,
        prior_attempt_7_rank_diagnostics=list(_ATTEMPT_7_RANK_DIAGNOSTICS),
        implementation_source=_CHECKPOINT_RESUME_IMPLEMENTATION_SOURCE,
        output=output,
    )
    assert payload["authorization_hash"] == authorization.authorization_hash
    loaded = load_optimizer_smoke_execution_authorization(output)
    assert type(loaded) is HweDecisionSft64kCheckpointResumeQualificationAuthorization
    with pytest.raises(ValueError, match="must not already exist"):
        authorize_checkpoint_resume_qualification(
            config=_CONFIG,
            preregistration_receipt=_PREREGISTRATION_RECEIPT,
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            prior_attempt_7_authorization=_ATTEMPT_7_AUTHORIZATION,
            prior_attempt_7_pass_report=_ATTEMPT_7_PASS_REPORT,
            prior_attempt_7_summary=_ATTEMPT_7_SUMMARY,
            prior_attempt_7_rank_diagnostics=list(_ATTEMPT_7_RANK_DIAGNOSTICS),
            implementation_source=_CHECKPOINT_RESUME_IMPLEMENTATION_SOURCE,
            output=output,
        )


@pytest.mark.skipif(
    not _attempt_7_pass_artifacts_present(),
    reason="optimizer attempt-7 pass evidence is not installed",
)
def test_checkpoint_resume_authorization_rejects_rank_evidence_drift(tmp_path: Path) -> None:
    changed = tmp_path / "changed-rank.json"
    changed.write_bytes(_ATTEMPT_7_RANK_DIAGNOSTICS[0].read_bytes() + b"\n")
    paths = (changed, *_ATTEMPT_7_RANK_DIAGNOSTICS[1:])

    with pytest.raises(ValueError, match="rank evidence 0 changed"):
        create_checkpoint_resume_qualification_authorization(
            load_optimizer_smoke_preregistration(_CONFIG),
            dataset_root=_QUALIFICATION_ROOT / "dataset",
            qualification_root=_QUALIFICATION_ROOT,
            config_path=_CONFIG,
            preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
            prior_attempt_7_authorization_path=_ATTEMPT_7_AUTHORIZATION,
            prior_attempt_7_pass_report_path=_ATTEMPT_7_PASS_REPORT,
            prior_attempt_7_summary_path=_ATTEMPT_7_SUMMARY,
            prior_attempt_7_rank_diagnostic_paths=paths,
            implementation_source_path=_CHECKPOINT_RESUME_IMPLEMENTATION_SOURCE,
        )
