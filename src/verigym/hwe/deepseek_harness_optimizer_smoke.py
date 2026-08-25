"""Fail-closed preregistration for the DeepSeek Harness 64K optimizer smoke."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.schemas.hwe import (
    HweDeepSeekHarnessDecisionSftDatasetManifestV4,
    HweDeepSeekHarnessDecisionSftExampleV4,
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

OptimizerSmokeExecutionAuthorization = (
    HweDecisionSft64kOptimizerSmokeExecutionAuthorization
    | HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization
    | HweDecisionSft64kOptimizerDiagnosticReplayAuthorization
    | HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization
    | HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization
    | HweDecisionSft64kOptimizerFullSmokeReplayAuthorization
    | HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization
    | HweDecisionSft64kCheckpointResumeQualificationAuthorization
)

V4_DATASET_HASH = "0acfe95a820d87310a87b6da104ba59e259ce754b19242f7c9b42937591c5139"
V4_MANIFEST_SHA256 = "60b1f2646c238efa2197d89c98875c1587a3be16e1c051f2227c3a22b8ae4fac"
V4_TRAIN_JSONL_SHA256 = "cab55d3cc7752b971904c88d8c11e93645c0b215af9beec40dd648bcfe7f1aa1"
QUALIFICATION_SUMMARY_SHA256 = "da521f3859e4d188c9ebd5d4f560300f896f394905ca864346666f5b9ce1d384"
GPU_QUALIFICATION_SHA256 = "c44b7068284f4e02d6e0ec44a9e89f56e886debbbc32a06525a4312388d14a62"
SCHEDULE_INDICES = (62, 76, 20, 61, 41, 43, 53, 61)
ORIGINAL_AUTHORIZATION_HASH = "e20d56f36cd847c3b5bba088016d09a651a689935c299c2f13f09796ff375be7"
ORIGINAL_FAILURE_REPORT_SHA256 = "138000280478730bcb39b43788565b464a637fe77cfce03c999194a4fc39832b"
RETRY_AUTHORIZATION_HASH = "68246c680006aa392a45de4beafa1c2f11a53566bcc9ec9323130ead3874b34e"
RETRY_FAILURE_REPORT_SHA256 = "bb35899a191bb71b7f4d6fa67a6a6d8a92a69b92a66fd3a709d2ed122f5e1a1b"
DIAGNOSTIC_AUTHORIZATION_HASH = "b7a9942c9226cc39f28d8e946aa70e796dc15e39c5d5b49d215617ce14cdbc22"
DIAGNOSTIC_FAILURE_REPORT_SHA256 = (
    "c50793fe6b724632784e533733a60181d2762ad02c25162391938fecf7c16fcb"
)
BF16_TOLERANCE_AUTHORIZATION_HASH = (
    "82d5d82cfcfd5099551cf3ac38dade72ace01c88e55f92e358856bddfac88224"
)
BF16_TOLERANCE_AUTHORIZATION_SHA256 = (
    "213015d673eb8f5f226a6eeceba52fc583bfb23aa19fd77286ad43f82fe983fe"
)
BF16_TOLERANCE_FAILURE_REPORT_SHA256 = (
    "4647b7564caf1ea7f090c7c96b3f499c8d82e4f9cab247b8a445cd5c7b230392"
)
BF16_TOLERANCE_RANK_DIAGNOSTIC_SHA256 = (
    "8fe9add5ab125bc8866ff748eae36c3b91be8be12032ca07407d4346cd94d591",
    "bff676e9921fc7aa9f1d60dc289520581982ec115d38cd48a195b81bd314b4f0",
    "d55014ffbede6b8a92b93f25fda4f06c2bf278f2840a072c9b7bdb620712a3d1",
    "f204cfe5fe18babaf41d05796eeb242935a522f13c5e9fe6df6d1f348e57d7a7",
)
AUTHORIZED_SCHEDULE_AUTHORIZATION_HASH = (
    "8ef0ae8e44cedb40f6967bc85475fd4483ebed860c6653e2ea0d2582bb26a7d2"
)
AUTHORIZED_SCHEDULE_AUTHORIZATION_SHA256 = (
    "acc637cd5326bbb3be4dff3a2227991bc4815fd58ba80dd69a317faec7a4b3e3"
)
AUTHORIZED_SCHEDULE_PASS_REPORT_SHA256 = (
    "c18ce989c41b68b2f3d93bba120857a4f488c0d0796e5aba7318847493299b71"
)
AUTHORIZED_SCHEDULE_RANK_DIAGNOSTIC_SHA256 = (
    "d4fe830ba8bcaa389d18c15eb73f9ee811d0efb63b4d6ae8732e86d00dfa37ec",
    "d338b63d08f50fbe8ac9366bb7e0c895c0fc6033463c687fa1cc80d4cb2d8ea3",
    "3c0619e36b3a506d5f0f7e7f214f78727065bf38a68533d124f0427a9549d99c",
    "59acab82347d6111684fb1f4c7f8e39fbc821a6d940ce6800c3edc795725b242",
)
FULL_SMOKE_AUTHORIZATION_HASH = "0b443189d11c9943687d6f8dd249a203132aba003b49606493292268a6c5b705"
FULL_SMOKE_AUTHORIZATION_SHA256 = "53ffc48bc61aec314e8e1235d556d43ce677446ae9c346439c5973c7a9d11fe9"
FULL_SMOKE_FAILURE_REPORT_SHA256 = (
    "1cf0b909b9adc9f945295dadf369c41add239e0e5f26acfeb7b643e8cedecf40"
)
FULL_SMOKE_RANK_DIAGNOSTIC_SHA256 = (
    "010f422e394ff78ea70e7c08852cd621f29d4ad6ca228fb5568386bf216dc999",
    "fff0e61babd2c713abd0dfcafbcf776258188c87be5988461fb0e9dd7d027d58",
    "adcf2d75933395eb132882c9c6a8f0d774df33a52f1decf7ed6aff28227f1aef",
    "be5861f1f01fd015a6f600e0d937f369dc853c1e3a34c98e70872e1517b74111",
    "4fd030805c52eb70736fa7a881460f560fe9c58a0f205fadf628b6def041cf1a",
    "1acf643479bb2590d4ce97bd4894f9be5af506e3697f9eaa76beae6a61cfe816",
    "5acf4d3eb47d40787dc5bb3c18db842ac432636a9977834c050c8ed1d31d7d2a",
    "ee2d3a7e920550d39f46f29d8a59b6192600b25d8d1981f7ca0b2385bab75c8d",
)
ATTEMPT_7_AUTHORIZATION_HASH = "a2329c519edd2010aa41bde88168b7f2c24e25714dafaf81e09bbcde3e4857c8"
ATTEMPT_7_AUTHORIZATION_SHA256 = "7c65340716337f174e86b7747818e6f00963848427077b1790ca6cd6457e16b8"
ATTEMPT_7_PASS_REPORT_SHA256 = "46cb4a151da1de3bf789024f2fe122528e1f5ef71984765ea477c31feae6af62"
ATTEMPT_7_SUMMARY_SHA256 = "f37d83e972055ce64aa75d81d715c53ff0399a6e655b86a18cd9d35da8ed1ca8"
ATTEMPT_7_RANK_DIAGNOSTIC_SHA256 = (
    "8ee20388886eb9c67adb25aabf12791b2af928dbcea04be1713802e4bb9362e5",
    "621bc3a0271f01d77189cf2a1d8a5213dc32e96168cb7ff4bdc9807a127d7296",
    "5122310b6435b902029b547534201cdee18f7b6c58a1c268f2eb1e5779c4c822",
    "d8ada04dc2ed3150d5b527a2930d351eee42e5b0674a2b05e661a1b23da97052",
    "9765a06b62ffec4082357c864a92d451c38674daf4a36e9147bfafb7e88a0f83",
    "29581ad8e84b35fce477b6d324278c7bf80aa8ab3be4c69f50bc3a0172813d33",
    "4ef475741ba69e519564b7bab3de7bfb11f8b51c2fdfd3222f64e1b885b3498c",
    "f18803abcb9002b319f07d03d10e8b307dba91ac32bf9f2f465048acd48f416e",
    "c913ee65cc64653c72dd6d3a378c8bfb9cb6ae1a37695f7f17cea5554a735433",
    "7322774c4e91eaf2ce8be599dbb655cc55c802bfe9eabc7d9097aefde0e4b0e5",
    "8bc4947d9eba6e36dd914aeb958cf636c7ff5c5e0d93712884381d8da1e5493b",
    "b11672e46fbe8db84a5f5150652c41949e31de4f2e4b8c4c376dc592a0400c67",
    "2660dd5b6df128cc0e52169b258117328abc084033ba61d2e3d1a52dd4a430db",
    "ae6d27fe29258fb6dd33f52110aa8bd4074458007308b6004e14b89e9db482ac",
    "cdc7f971e7acf754e3d9e136ce5c628691f4c8380372c33f1888df61c9308776",
    "65bd351a261f6d5e81b68e2ac65b9fa23a9ed26910a2504bb3e688b29debe992",
    "c94c050b4a8945145cc530d0f9e0a808a76aa7cf6c93603757340daeb977fa10",
    "4703003c805e6d1999a699c6c7e6a85bd64039d0c3ed70b0fc935b707e351cb4",
    "c81359468bdeba2f7a5767a043921d535d8e9f6308a5775af185818aeaa2a8f3",
    "675e9966b79027fbbbc7509aff6b7fd869863d5d8a93d40a21fae3a15d2c9ca7",
    "5574c6a42844183343607e3c5eef19c1eb5ae2d7b2802489692532d7009b4972",
    "6a904dede03994ba47816831c35668996bdb573d631f61fdcb509c620caf05e7",
    "5704aa4e892565c8ccc7cc3b72ebd0070f4dced25d938e6dfb9f84f290be2048",
    "1a0a93e5b25dc54b15d866a6993639b02709a9c43ae06e024f4f5c1e4aeb78c5",
    "ebf75f4c7d6ae0136c66a61076d2f1cd8cb9783cf407229a0130dc9d5ef8b861",
    "b8e1fb8c06310c532e21e5b8c3d270d30807534389cf28801339167f0421ea6b",
    "c510f32871ce4c985e3c65b04a4a5d5df8e7c4709d31650c68a7f2264c7fe5cf",
    "eb6027f256956f7486cd5a64d2d5e2c41ce87e92a12d5e09794edc9fd5f33945",
    "e46f4199b13c63ce40080ab551b89f39d2bd88dba7eb97e560e660240d8ea73a",
    "923b71cbb065fa76dd859ac425fb7ce84507421716983aa5b7b732f423e33f64",
    "bfa604f43e9c9909b28e0b94bd9aea0806065f8a68b53e59637b52861bf4f92c",
    "cc568f8e08be5a37b92da15e0e4ace44a599ba59d16c121d74f070d84f0fd47e",
)
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_DATASET_BYTES = 16 * 1024 * 1024


def load_optimizer_smoke_preregistration(
    path: Path,
) -> HweDecisionSft64kOptimizerSmokePreregistration:
    """Load one sealed preregistration without accepting symlinks or extra fields."""

    payload = _read_regular(path, max_bytes=_MAX_CONFIG_BYTES)
    return HweDecisionSft64kOptimizerSmokePreregistration.model_validate_json(payload)


def validate_optimizer_smoke_preregistration(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    *,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
) -> dict[str, Any]:
    """Bind the schedule to v4 and the clean zero-step GPU qualification evidence."""

    dataset = _safe_directory(dataset_root, label="64K v4 dataset")
    qualification = _safe_directory(qualification_root, label="64K qualification")
    config_payload = _read_regular(config_path, max_bytes=_MAX_CONFIG_BYTES)
    reparsed = HweDecisionSft64kOptimizerSmokePreregistration.model_validate_json(config_payload)
    if reparsed != preregistration:
        raise ValueError("optimizer smoke preregistration object differs from its config bytes")

    manifest_payload = _read_regular(
        dataset / "dataset-manifest.json",
        max_bytes=_MAX_DATASET_BYTES,
    )
    train_payload = _read_regular(dataset / "train.jsonl", max_bytes=_MAX_DATASET_BYTES)
    if hashlib.sha256(manifest_payload).hexdigest() != V4_MANIFEST_SHA256:
        raise ValueError("optimizer smoke source v4 manifest SHA-256 changed")
    if hashlib.sha256(train_payload).hexdigest() != V4_TRAIN_JSONL_SHA256:
        raise ValueError("optimizer smoke source v4 train JSONL SHA-256 changed")
    manifest = HweDeepSeekHarnessDecisionSftDatasetManifestV4.model_validate_json(manifest_payload)
    if manifest.dataset_hash != V4_DATASET_HASH:
        raise ValueError("optimizer smoke source v4 dataset hash changed")
    raw_lines = train_payload.decode("utf-8").splitlines()
    if len(raw_lines) != 83 or any(not line for line in raw_lines):
        raise ValueError("optimizer smoke source v4 must contain exactly 83 records")
    rows = [HweDeepSeekHarnessDecisionSftExampleV4.model_validate_json(line) for line in raw_lines]
    if [row.record_hash for row in rows] != manifest.record_hashes:
        raise ValueError("optimizer smoke source v4 row order or identity changed")
    _validate_schedule(preregistration, rows)

    summary_payload = _read_regular(
        qualification / "qualification-summary.json",
        max_bytes=_MAX_CONFIG_BYTES,
    )
    gpu_payload = _read_regular(
        qualification / "gpu-qualification-primary.json",
        max_bytes=_MAX_CONFIG_BYTES,
    )
    if hashlib.sha256(summary_payload).hexdigest() != QUALIFICATION_SUMMARY_SHA256:
        raise ValueError("optimizer smoke qualification summary SHA-256 changed")
    if hashlib.sha256(gpu_payload).hexdigest() != GPU_QUALIFICATION_SHA256:
        raise ValueError("optimizer smoke GPU qualification SHA-256 changed")
    summary = _json_object(summary_payload, label="qualification summary")
    gpu = _json_object(gpu_payload, label="GPU qualification")
    _validate_qualification(summary, gpu)

    receipt_base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_decision_sft_64k_optimizer_smoke_preregistration_receipt_v1",
        "status": "preregistered_not_started",
        "preregistration_hash": preregistration.preregistration_hash,
        "config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "source_v3_dataset_hash": preregistration.source_v3_dataset_hash,
        "source_v4_dataset_hash": manifest.dataset_hash,
        "source_v4_manifest_sha256": V4_MANIFEST_SHA256,
        "source_v4_train_jsonl_sha256": V4_TRAIN_JSONL_SHA256,
        "qualification_summary_sha256": QUALIFICATION_SUMMARY_SHA256,
        "gpu_qualification_sha256": GPU_QUALIFICATION_SHA256,
        "schedule_hash": preregistration.schedule_hash,
        "schedule_indices": list(SCHEDULE_INDICES),
        "schedule_record_hashes": [item.source_v4_record_hash for item in preregistration.schedule],
        "step_count": preregistration.step_count,
        "longest_record_index": 61,
        "longest_record_tokens": 50_117,
        "longest_repeat_steps": [4, 8],
        "actual_optimizer_execution_authorized": False,
        "training_started": False,
        "optimizer_steps": 0,
        "checkpoint_written": False,
        "adapter_written": False,
        "production_training_ready": False,
        "new_hpc_jobs_submitted": False,
        "existing_allocation_modified": False,
    }
    return {**receipt_base, "receipt_hash": content_hash(receipt_base)}


def create_optimizer_smoke_execution_authorization(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    *,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
) -> HweDecisionSft64kOptimizerSmokeExecutionAuthorization:
    """Create the one-use receipt only after all preregistration evidence is revalidated."""

    expected_receipt = validate_optimizer_smoke_preregistration(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
    )
    receipt_payload = _read_regular(
        preregistration_receipt_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    if _json_object(receipt_payload, label="preregistration receipt") != expected_receipt:
        raise ValueError("optimizer smoke preregistration receipt differs from frozen evidence")
    config_payload = _read_regular(config_path, max_bytes=_MAX_CONFIG_BYTES)
    authorization_base = {
        "schema_version": "1.0",
        "format_id": ("verigym_hwe_decision_sft_64k_optimizer_smoke_execution_authorization_v1"),
        "status": "authorized_for_single_execution",
        "authorization_basis": "explicit_user_instruction",
        "authorization_scope": "single_preregistered_execution",
        "preregistration_hash": preregistration.preregistration_hash,
        "preregistration_config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "preregistration_receipt_hash": expected_receipt["receipt_hash"],
        "preregistration_receipt_sha256": hashlib.sha256(receipt_payload).hexdigest(),
        "source_v4_dataset_hash": preregistration.source_v4_dataset_hash,
        "schedule_hash": preregistration.schedule_hash,
        "schedule_indices": list(SCHEDULE_INDICES),
        "optimizer_steps_authorized": preregistration.step_count,
        "execution_authorized": True,
        "checkpoint_allowed": False,
        "adapter_allowed": False,
        "offload_fallback_allowed": False,
        "new_hpc_jobs_allowed": preregistration.new_hpc_jobs_allowed,
        "release_existing_allocation": preregistration.release_existing_allocation,
        "existing_lsf_job_id": preregistration.existing_lsf_job_id,
        "planned_host": preregistration.planned_host,
        "selected_gpu_indices": list(preregistration.selected_gpu_indices),
        "production_training_ready": False,
    }
    return HweDecisionSft64kOptimizerSmokeExecutionAuthorization.model_validate(
        {**authorization_base, "authorization_hash": content_hash(authorization_base)}
    )


def load_optimizer_smoke_execution_authorization(
    path: Path,
) -> OptimizerSmokeExecutionAuthorization:
    """Load a sealed execution authorization from a safe regular file."""

    payload = _read_regular(path, max_bytes=_MAX_CONFIG_BYTES)
    value = _json_object(payload, label="execution authorization")
    if value.get("format_id") == (
        "verigym_hwe_decision_sft_64k_checkpoint_resume_qualification_authorization_v1"
    ):
        return HweDecisionSft64kCheckpointResumeQualificationAuthorization.model_validate(value)
    if value.get("format_id") == (
        "verigym_hwe_decision_sft_64k_optimizer_full_smoke_bf16_tolerance_replay_authorization_v1"
    ):
        return HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization.model_validate(
            value
        )
    if value.get("format_id") == (
        "verigym_hwe_decision_sft_64k_optimizer_full_smoke_replay_authorization_v1"
    ):
        return HweDecisionSft64kOptimizerFullSmokeReplayAuthorization.model_validate(value)
    if value.get("format_id") == (
        "verigym_hwe_decision_sft_64k_optimizer_authorized_schedule_replay_authorization_v1"
    ):
        return HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization.model_validate(value)
    if value.get("format_id") == (
        "verigym_hwe_decision_sft_64k_optimizer_bf16_tolerance_replay_authorization_v1"
    ):
        return HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization.model_validate(value)
    if value.get("format_id") == (
        "verigym_hwe_decision_sft_64k_optimizer_diagnostic_replay_authorization_v1"
    ):
        return HweDecisionSft64kOptimizerDiagnosticReplayAuthorization.model_validate(value)
    if value.get("format_id") == (
        "verigym_hwe_decision_sft_64k_optimizer_smoke_execution_retry_authorization_v1"
    ):
        return HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization.model_validate(value)
    return HweDecisionSft64kOptimizerSmokeExecutionAuthorization.model_validate(value)


def validate_optimizer_smoke_execution_authorization(
    authorization: HweDecisionSft64kOptimizerSmokeExecutionAuthorization,
    *,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
) -> None:
    """Reject authorization drift against the frozen config, receipt, dataset, or qualification."""

    expected = create_optimizer_smoke_execution_authorization(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
        preregistration_receipt_path=preregistration_receipt_path,
    )
    if authorization != expected:
        raise ValueError("optimizer smoke execution authorization differs from frozen evidence")


def create_optimizer_smoke_execution_retry_authorization(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    *,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
    prior_authorization_path: Path,
    prior_failure_report_path: Path,
    implementation_source_path: Path,
) -> HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization:
    """Authorize a replacement only when the first attempt provably took zero steps."""

    prior = load_optimizer_smoke_execution_authorization(prior_authorization_path)
    if not isinstance(prior, HweDecisionSft64kOptimizerSmokeExecutionAuthorization) or isinstance(
        prior,
        HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization,
    ):
        raise ValueError("optimizer smoke retry cannot replace another retry authorization")
    validate_optimizer_smoke_execution_authorization(
        prior,
        preregistration=preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
        preregistration_receipt_path=preregistration_receipt_path,
    )
    failure_payload = _read_regular(prior_failure_report_path, max_bytes=_MAX_CONFIG_BYTES)
    failure = _json_object(failure_payload, label="prior failure report")
    _validate_zero_step_implementation_failure(failure, authorization=prior)
    implementation_payload = _read_regular(
        implementation_source_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    retry_base = prior.model_dump(mode="json", exclude={"authorization_hash"})
    retry_base.update(
        {
            "format_id": (
                "verigym_hwe_decision_sft_64k_optimizer_smoke_execution_retry_authorization_v1"
            ),
            "status": "authorized_zero_step_implementation_retry",
            "authorization_basis": ("explicit_user_instruction_zero_step_implementation_retry"),
            "attempt": 2,
            "replaces_authorization_hash": prior.authorization_hash,
            "prior_failure_report_sha256": hashlib.sha256(failure_payload).hexdigest(),
            "prior_optimizer_steps_confirmed": 0,
            "replacement_reason": "zero_optimizer_step_implementation_failure",
            "implementation_fix": "replace_unsupported_tensor_maximum_inplace",
            "implementation_source_sha256": hashlib.sha256(implementation_payload).hexdigest(),
        }
    )
    return HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization.model_validate(
        {**retry_base, "authorization_hash": content_hash(retry_base)}
    )


def validate_optimizer_smoke_execution_retry_authorization(
    authorization: HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization,
    *,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
    prior_authorization_path: Path,
    prior_failure_report_path: Path,
    implementation_source_path: Path,
) -> None:
    """Reject a retry not bound to the exact zero-step failure and fixed source."""

    expected = create_optimizer_smoke_execution_retry_authorization(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
        preregistration_receipt_path=preregistration_receipt_path,
        prior_authorization_path=prior_authorization_path,
        prior_failure_report_path=prior_failure_report_path,
        implementation_source_path=implementation_source_path,
    )
    if authorization != expected:
        raise ValueError("optimizer smoke retry authorization differs from frozen failure evidence")


def create_optimizer_diagnostic_replay_authorization(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    *,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
    prior_authorization_path: Path,
    prior_failure_report_path: Path,
    prior_retry_authorization_path: Path,
    prior_retry_failure_report_path: Path,
    instrumentation_source_path: Path,
) -> HweDecisionSft64kOptimizerDiagnosticReplayAuthorization:
    """Seal one diagnostic step after proving both historical attempts and current source."""

    expected_receipt = validate_optimizer_smoke_preregistration(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
    )
    receipt_payload = _read_regular(preregistration_receipt_path, max_bytes=_MAX_CONFIG_BYTES)
    if _json_object(receipt_payload, label="preregistration receipt") != expected_receipt:
        raise ValueError(
            "optimizer diagnostic preregistration receipt differs from frozen evidence"
        )

    prior = load_optimizer_smoke_execution_authorization(prior_authorization_path)
    if not isinstance(prior, HweDecisionSft64kOptimizerSmokeExecutionAuthorization) or isinstance(
        prior,
        HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization,
    ):
        raise ValueError("optimizer diagnostic requires the original execution authorization")
    validate_optimizer_smoke_execution_authorization(
        prior,
        preregistration=preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
        preregistration_receipt_path=preregistration_receipt_path,
    )
    if prior.authorization_hash != ORIGINAL_AUTHORIZATION_HASH:
        raise ValueError("optimizer diagnostic original authorization identity changed")
    prior_failure_payload = _read_regular(
        prior_failure_report_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    if hashlib.sha256(prior_failure_payload).hexdigest() != ORIGINAL_FAILURE_REPORT_SHA256:
        raise ValueError("optimizer diagnostic original failure report SHA-256 changed")
    _validate_zero_step_implementation_failure(
        _json_object(prior_failure_payload, label="original failure report"),
        authorization=prior,
    )

    retry = load_optimizer_smoke_execution_authorization(prior_retry_authorization_path)
    if not isinstance(retry, HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization):
        raise ValueError("optimizer diagnostic requires the registered retry authorization")
    if (
        retry.authorization_hash != RETRY_AUTHORIZATION_HASH
        or retry.replaces_authorization_hash != prior.authorization_hash
        or retry.prior_failure_report_sha256 != ORIGINAL_FAILURE_REPORT_SHA256
        or retry.prior_optimizer_steps_confirmed != 0
    ):
        raise ValueError("optimizer diagnostic retry authorization chain changed")
    retry_failure_payload = _read_regular(
        prior_retry_failure_report_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    if hashlib.sha256(retry_failure_payload).hexdigest() != RETRY_FAILURE_REPORT_SHA256:
        raise ValueError("optimizer diagnostic retry failure report SHA-256 changed")
    _validate_one_step_post_invariant_failure(
        _json_object(retry_failure_payload, label="retry failure report"),
        authorization=retry,
    )

    source_payload = _read_regular(instrumentation_source_path, max_bytes=_MAX_CONFIG_BYTES)
    config_payload = _read_regular(config_path, max_bytes=_MAX_CONFIG_BYTES)
    first_step = preregistration.schedule[0]
    authorization_base = {
        "schema_version": "1.0",
        "format_id": ("verigym_hwe_decision_sft_64k_optimizer_diagnostic_replay_authorization_v1"),
        "status": "authorized_for_single_step_diagnostic_replay",
        "authorization_basis": "explicit_user_instruction_single_step_diagnostic_replay",
        "authorization_scope": "single_record_single_optimizer_step_diagnostic",
        "attempt": 3,
        "preregistration_hash": preregistration.preregistration_hash,
        "preregistration_config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "preregistration_receipt_hash": expected_receipt["receipt_hash"],
        "preregistration_receipt_sha256": hashlib.sha256(receipt_payload).hexdigest(),
        "source_v4_dataset_hash": preregistration.source_v4_dataset_hash,
        "schedule_hash": preregistration.schedule_hash,
        "source_v4_record_index": first_step.source_v4_record_index,
        "source_v4_record_hash": first_step.source_v4_record_hash,
        "task_id": first_step.task_id,
        "token_count": first_step.token_count,
        "optimizer_steps_authorized": 1,
        "execution_authorized": True,
        "checkpoint_allowed": False,
        "adapter_allowed": False,
        "offload_fallback_allowed": False,
        "new_hpc_jobs_allowed": False,
        "release_existing_allocation": False,
        "existing_lsf_job_id": preregistration.existing_lsf_job_id,
        "planned_host": preregistration.planned_host,
        "selected_gpu_indices": list(preregistration.selected_gpu_indices),
        "prior_authorization_hash": prior.authorization_hash,
        "prior_failure_report_sha256": hashlib.sha256(prior_failure_payload).hexdigest(),
        "prior_retry_authorization_hash": retry.authorization_hash,
        "prior_retry_failure_report_sha256": hashlib.sha256(retry_failure_payload).hexdigest(),
        "prior_retry_optimizer_steps_confirmed": 1,
        "diagnostic_instrumentation_source_sha256": hashlib.sha256(source_payload).hexdigest(),
        "development_training_ready": False,
        "production_training_ready": False,
    }
    return HweDecisionSft64kOptimizerDiagnosticReplayAuthorization.model_validate(
        {**authorization_base, "authorization_hash": content_hash(authorization_base)}
    )


def validate_optimizer_diagnostic_replay_authorization(
    authorization: HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
    *,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
    prior_authorization_path: Path,
    prior_failure_report_path: Path,
    prior_retry_authorization_path: Path,
    prior_retry_failure_report_path: Path,
    instrumentation_source_path: Path,
) -> None:
    """Reject any diagnostic authorization that is not the exact evidence-derived receipt."""

    expected = create_optimizer_diagnostic_replay_authorization(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
        preregistration_receipt_path=preregistration_receipt_path,
        prior_authorization_path=prior_authorization_path,
        prior_failure_report_path=prior_failure_report_path,
        prior_retry_authorization_path=prior_retry_authorization_path,
        prior_retry_failure_report_path=prior_retry_failure_report_path,
        instrumentation_source_path=instrumentation_source_path,
    )
    if authorization != expected:
        raise ValueError("optimizer diagnostic authorization differs from frozen evidence")


def create_optimizer_bf16_tolerance_replay_authorization(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    *,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
    prior_diagnostic_authorization_path: Path,
    prior_diagnostic_failure_report_path: Path,
    implementation_source_path: Path,
) -> HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization:
    """Seal one BF16-aware replay after proving the exact diagnostic failure."""

    expected_receipt = validate_optimizer_smoke_preregistration(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
    )
    receipt_payload = _read_regular(preregistration_receipt_path, max_bytes=_MAX_CONFIG_BYTES)
    if _json_object(receipt_payload, label="preregistration receipt") != expected_receipt:
        raise ValueError("optimizer BF16 replay preregistration receipt changed")

    prior_payload = _read_regular(
        prior_diagnostic_authorization_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    prior = load_optimizer_smoke_execution_authorization(prior_diagnostic_authorization_path)
    if type(prior) is not HweDecisionSft64kOptimizerDiagnosticReplayAuthorization:
        raise ValueError("optimizer BF16 replay requires the attempt-3 diagnostic authorization")
    if (
        prior.authorization_hash != DIAGNOSTIC_AUTHORIZATION_HASH
        or hashlib.sha256(prior_payload).hexdigest()
        != "5ec32ef199fd091d8aad1f52d62c3b797456e34b323052db5797b3dc4fcaf58c"
        or prior.diagnostic_instrumentation_source_sha256
        != "242a910cfa104740ffa4e87eb2f332d96dbaace31cabe59046d3b2bfa207bea9"
    ):
        raise ValueError("optimizer BF16 replay diagnostic authorization identity changed")

    prior_failure_payload = _read_regular(
        prior_diagnostic_failure_report_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    if hashlib.sha256(prior_failure_payload).hexdigest() != DIAGNOSTIC_FAILURE_REPORT_SHA256:
        raise ValueError("optimizer BF16 replay diagnostic failure report SHA-256 changed")
    _validate_diagnostic_rounding_failure(
        _json_object(prior_failure_payload, label="diagnostic failure report"),
        authorization=prior,
    )

    source_payload = _read_regular(implementation_source_path, max_bytes=_MAX_CONFIG_BYTES)
    config_payload = _read_regular(config_path, max_bytes=_MAX_CONFIG_BYTES)
    first_step = preregistration.schedule[0]
    authorization_base = {
        "schema_version": "1.0",
        "format_id": (
            "verigym_hwe_decision_sft_64k_optimizer_bf16_tolerance_replay_authorization_v1"
        ),
        "status": "authorized_for_single_step_bf16_tolerance_replay",
        "authorization_basis": "explicit_user_instruction_execute_bf16_tolerance_replay",
        "authorization_scope": "single_record_single_optimizer_step_bf16_tolerance",
        "attempt": 4,
        "preregistration_hash": preregistration.preregistration_hash,
        "preregistration_config_sha256": hashlib.sha256(config_payload).hexdigest(),
        "preregistration_receipt_hash": expected_receipt["receipt_hash"],
        "preregistration_receipt_sha256": hashlib.sha256(receipt_payload).hexdigest(),
        "source_v4_dataset_hash": preregistration.source_v4_dataset_hash,
        "schedule_hash": preregistration.schedule_hash,
        "source_v4_record_index": first_step.source_v4_record_index,
        "source_v4_record_hash": first_step.source_v4_record_hash,
        "task_id": first_step.task_id,
        "token_count": first_step.token_count,
        "optimizer_steps_authorized": 1,
        "execution_authorized": True,
        "checkpoint_allowed": False,
        "adapter_allowed": False,
        "offload_fallback_allowed": False,
        "new_hpc_jobs_allowed": False,
        "release_existing_allocation": False,
        "existing_lsf_job_id": preregistration.existing_lsf_job_id,
        "planned_host": preregistration.planned_host,
        "selected_gpu_indices": list(preregistration.selected_gpu_indices),
        "prior_authorization_hash": prior.prior_authorization_hash,
        "prior_failure_report_sha256": prior.prior_failure_report_sha256,
        "prior_retry_authorization_hash": prior.prior_retry_authorization_hash,
        "prior_retry_failure_report_sha256": prior.prior_retry_failure_report_sha256,
        "prior_retry_optimizer_steps_confirmed": 1,
        "diagnostic_instrumentation_source_sha256": hashlib.sha256(source_payload).hexdigest(),
        "development_training_ready": False,
        "production_training_ready": False,
        "replaces_authorization_hash": prior.authorization_hash,
        "prior_diagnostic_authorization_sha256": hashlib.sha256(prior_payload).hexdigest(),
        "prior_diagnostic_failure_report_sha256": hashlib.sha256(prior_failure_payload).hexdigest(),
        "prior_diagnostic_instrumentation_source_sha256": (
            prior.diagnostic_instrumentation_source_sha256
        ),
        "prior_diagnostic_optimizer_steps_confirmed": 1,
        "prior_failed_invariant": "post_clip_global_norm_within_limit",
        "gradient_clip_target": 1.0,
        "bfloat16_epsilon": 0.0078125,
        "tolerance_multiplier": 2,
        "post_clip_global_norm_relative_tolerance": 0.015625,
        "post_clip_global_norm_acceptance_lte": 1.015625,
        "tolerance_basis": "two_bfloat16_eps_relative_rounding_margin",
        "tolerance_tuned_to_observed_value": False,
    }
    return HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization.model_validate(
        {**authorization_base, "authorization_hash": content_hash(authorization_base)}
    )


def validate_optimizer_bf16_tolerance_replay_authorization(
    authorization: HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
    **kwargs: Any,
) -> None:
    """Reject BF16 replay authorization or evidence drift."""

    expected = create_optimizer_bf16_tolerance_replay_authorization(**kwargs)
    if authorization != expected:
        raise ValueError("optimizer BF16 tolerance authorization differs from frozen evidence")


def create_optimizer_authorized_schedule_replay_authorization(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    *,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
    prior_bf16_tolerance_authorization_path: Path,
    prior_bf16_tolerance_failure_report_path: Path,
    prior_bf16_rank_diagnostic_paths: tuple[Path, Path, Path, Path],
    implementation_source_path: Path,
) -> HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization:
    """Seal one replay after proving the prior step passed before a schedule bug."""

    expected_receipt = validate_optimizer_smoke_preregistration(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
    )
    receipt_payload = _read_regular(preregistration_receipt_path, max_bytes=_MAX_CONFIG_BYTES)
    if _json_object(receipt_payload, label="preregistration receipt") != expected_receipt:
        raise ValueError("optimizer authorized-schedule replay preregistration receipt changed")

    prior_payload = _read_regular(
        prior_bf16_tolerance_authorization_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    prior = load_optimizer_smoke_execution_authorization(prior_bf16_tolerance_authorization_path)
    if type(prior) is not HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization:
        raise ValueError("optimizer authorized-schedule replay requires attempt-4 authorization")
    if (
        prior.authorization_hash != BF16_TOLERANCE_AUTHORIZATION_HASH
        or hashlib.sha256(prior_payload).hexdigest() != BF16_TOLERANCE_AUTHORIZATION_SHA256
    ):
        raise ValueError("optimizer authorized-schedule prior authorization changed")

    failure_payload = _read_regular(
        prior_bf16_tolerance_failure_report_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    if hashlib.sha256(failure_payload).hexdigest() != BF16_TOLERANCE_FAILURE_REPORT_SHA256:
        raise ValueError("optimizer authorized-schedule prior failure report changed")
    _validate_bf16_authorized_schedule_failure(
        _json_object(failure_payload, label="BF16 tolerance failure report"),
        authorization=prior,
    )

    rank_hashes: list[str] = []
    for rank, path in enumerate(prior_bf16_rank_diagnostic_paths):
        payload = _read_regular(path, max_bytes=_MAX_CONFIG_BYTES)
        rank_hash = hashlib.sha256(payload).hexdigest()
        if rank_hash != BF16_TOLERANCE_RANK_DIAGNOSTIC_SHA256[rank]:
            raise ValueError(f"optimizer authorized-schedule rank {rank} evidence changed")
        _validate_bf16_passing_rank_diagnostic(
            _json_object(payload, label=f"BF16 tolerance rank {rank} diagnostic"),
            rank=rank,
        )
        rank_hashes.append(rank_hash)

    source_payload = _read_regular(implementation_source_path, max_bytes=_MAX_CONFIG_BYTES)
    config_payload = _read_regular(config_path, max_bytes=_MAX_CONFIG_BYTES)
    first_step = preregistration.schedule[0]
    authorization_base = prior.model_dump(mode="json", exclude={"authorization_hash"})
    authorization_base.update(
        {
            "format_id": (
                "verigym_hwe_decision_sft_64k_optimizer_authorized_schedule_replay_authorization_v1"
            ),
            "status": "authorized_for_single_step_authorized_schedule_replay",
            "authorization_basis": (
                "explicit_user_instruction_and_standing_same_scope_authorization"
            ),
            "authorization_scope": ("single_record_single_optimizer_step_authorized_schedule"),
            "attempt": 5,
            "preregistration_config_sha256": hashlib.sha256(config_payload).hexdigest(),
            "preregistration_receipt_hash": expected_receipt["receipt_hash"],
            "preregistration_receipt_sha256": hashlib.sha256(receipt_payload).hexdigest(),
            "source_v4_record_index": first_step.source_v4_record_index,
            "source_v4_record_hash": first_step.source_v4_record_hash,
            "task_id": first_step.task_id,
            "token_count": first_step.token_count,
            "diagnostic_instrumentation_source_sha256": hashlib.sha256(source_payload).hexdigest(),
            "replaces_authorization_hash": prior.authorization_hash,
            "prior_bf16_tolerance_authorization_sha256": hashlib.sha256(prior_payload).hexdigest(),
            "prior_bf16_tolerance_failure_report_sha256": hashlib.sha256(
                failure_payload
            ).hexdigest(),
            "prior_bf16_tolerance_optimizer_steps_confirmed": 1,
            "prior_bf16_post_step_invariants_all_passed": True,
            "prior_second_optimizer_step_executed": False,
            "prior_bf16_rank_diagnostic_sha256": rank_hashes,
            "implementation_fix": "execution_loop_uses_authorized_schedule",
        }
    )
    return HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization.model_validate(
        {
            **authorization_base,
            "authorization_hash": content_hash(authorization_base),
        }
    )


def validate_optimizer_authorized_schedule_replay_authorization(
    authorization: HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization,
    **kwargs: Any,
) -> None:
    """Reject attempt-5 authorization or any bound evidence drift."""

    expected = create_optimizer_authorized_schedule_replay_authorization(**kwargs)
    if authorization != expected:
        raise ValueError("optimizer authorized-schedule authorization differs from evidence")


def create_optimizer_full_smoke_replay_authorization(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    *,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
    prior_authorized_schedule_authorization_path: Path,
    prior_authorized_schedule_pass_report_path: Path,
    prior_authorized_schedule_rank_diagnostic_paths: tuple[Path, Path, Path, Path],
    implementation_source_path: Path,
) -> HweDecisionSft64kOptimizerFullSmokeReplayAuthorization:
    """Seal the full eight-step smoke after proving the repaired one-step pass."""

    original = create_optimizer_smoke_execution_authorization(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
        preregistration_receipt_path=preregistration_receipt_path,
    )
    prior_payload = _read_regular(
        prior_authorized_schedule_authorization_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    prior = load_optimizer_smoke_execution_authorization(
        prior_authorized_schedule_authorization_path
    )
    if type(prior) is not HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization:
        raise ValueError("optimizer full smoke requires the attempt-5 authorization")
    if (
        prior.authorization_hash != AUTHORIZED_SCHEDULE_AUTHORIZATION_HASH
        or hashlib.sha256(prior_payload).hexdigest() != AUTHORIZED_SCHEDULE_AUTHORIZATION_SHA256
    ):
        raise ValueError("optimizer full smoke prior authorization changed")

    report_payload = _read_regular(
        prior_authorized_schedule_pass_report_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    if hashlib.sha256(report_payload).hexdigest() != AUTHORIZED_SCHEDULE_PASS_REPORT_SHA256:
        raise ValueError("optimizer full smoke prior pass report changed")
    _validate_authorized_schedule_pass_report(
        _json_object(report_payload, label="authorized-schedule pass report"),
        authorization=prior,
    )

    rank_hashes: list[str] = []
    for rank, path in enumerate(prior_authorized_schedule_rank_diagnostic_paths):
        payload = _read_regular(path, max_bytes=_MAX_CONFIG_BYTES)
        rank_hash = hashlib.sha256(payload).hexdigest()
        if rank_hash != AUTHORIZED_SCHEDULE_RANK_DIAGNOSTIC_SHA256[rank]:
            raise ValueError(f"optimizer full smoke rank {rank} evidence changed")
        _validate_authorized_schedule_passing_rank_diagnostic(
            _json_object(payload, label=f"authorized-schedule rank {rank} diagnostic"),
            rank=rank,
        )
        rank_hashes.append(rank_hash)

    source_payload = _read_regular(implementation_source_path, max_bytes=_MAX_CONFIG_BYTES)
    source_sha256 = hashlib.sha256(source_payload).hexdigest()
    if source_sha256 != "f024e74dc3ba74f97c9132812b73a299fa3ca7be076e66b0eb0a177276e37c61":
        raise ValueError("optimizer full smoke authorized-schedule implementation changed")
    authorization_base = original.model_dump(mode="json", exclude={"authorization_hash"})
    authorization_base.update(
        {
            "format_id": (
                "verigym_hwe_decision_sft_64k_optimizer_full_smoke_replay_authorization_v1"
            ),
            "status": "authorized_for_full_eight_step_smoke_replay",
            "authorization_basis": (
                "explicit_user_instruction_execute_full_eight_step_optimizer_smoke"
            ),
            "authorization_scope": "single_preregistered_eight_step_optimizer_smoke",
            "attempt": 6,
            "replaces_authorization_hash": prior.authorization_hash,
            "prior_authorized_schedule_authorization_sha256": hashlib.sha256(
                prior_payload
            ).hexdigest(),
            "prior_authorized_schedule_pass_report_sha256": hashlib.sha256(
                report_payload
            ).hexdigest(),
            "prior_authorized_schedule_optimizer_steps_confirmed": 1,
            "prior_authorized_schedule_invariants_all_passed": True,
            "prior_authorized_schedule_rank_diagnostic_sha256": rank_hashes,
            "implementation_fix": "execution_loop_uses_authorized_schedule",
            "implementation_source_sha256": source_sha256,
        }
    )
    return HweDecisionSft64kOptimizerFullSmokeReplayAuthorization.model_validate(
        {
            **authorization_base,
            "authorization_hash": content_hash(authorization_base),
        }
    )


def validate_optimizer_full_smoke_replay_authorization(
    authorization: HweDecisionSft64kOptimizerFullSmokeReplayAuthorization,
    **kwargs: Any,
) -> None:
    """Reject attempt-6 authorization or any prior passing evidence drift."""

    expected = create_optimizer_full_smoke_replay_authorization(**kwargs)
    if authorization != expected:
        raise ValueError("optimizer full-smoke authorization differs from evidence")


def create_optimizer_full_smoke_bf16_tolerance_replay_authorization(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    *,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
    prior_full_smoke_authorization_path: Path,
    prior_full_smoke_failure_report_path: Path,
    prior_full_smoke_rank_diagnostic_paths: tuple[
        Path,
        Path,
        Path,
        Path,
        Path,
        Path,
        Path,
        Path,
    ],
    implementation_source_path: Path,
) -> HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization:
    """Seal attempt 7 against the exact attempt-6 BF16-only failure."""

    expected_receipt = validate_optimizer_smoke_preregistration(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
    )
    receipt_payload = _read_regular(preregistration_receipt_path, max_bytes=_MAX_CONFIG_BYTES)
    if _json_object(receipt_payload, label="preregistration receipt") != expected_receipt:
        raise ValueError("optimizer full-smoke BF16 replay preregistration receipt changed")

    prior_payload = _read_regular(
        prior_full_smoke_authorization_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    prior = load_optimizer_smoke_execution_authorization(prior_full_smoke_authorization_path)
    if type(prior) is not HweDecisionSft64kOptimizerFullSmokeReplayAuthorization:
        raise ValueError("optimizer full-smoke BF16 replay requires attempt-6 authorization")
    if (
        prior.authorization_hash != FULL_SMOKE_AUTHORIZATION_HASH
        or hashlib.sha256(prior_payload).hexdigest() != FULL_SMOKE_AUTHORIZATION_SHA256
    ):
        raise ValueError("optimizer full-smoke BF16 prior authorization changed")

    failure_payload = _read_regular(
        prior_full_smoke_failure_report_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    if hashlib.sha256(failure_payload).hexdigest() != FULL_SMOKE_FAILURE_REPORT_SHA256:
        raise ValueError("optimizer full-smoke BF16 failure report changed")
    _validate_full_smoke_bf16_tolerance_failure(
        _json_object(failure_payload, label="full-smoke failure report"),
        authorization=prior,
    )

    rank_hashes: list[str] = []
    for position, path in enumerate(prior_full_smoke_rank_diagnostic_paths):
        payload = _read_regular(path, max_bytes=_MAX_CONFIG_BYTES)
        rank_hash = hashlib.sha256(payload).hexdigest()
        if rank_hash != FULL_SMOKE_RANK_DIAGNOSTIC_SHA256[position]:
            raise ValueError(f"optimizer full-smoke BF16 rank evidence {position} changed")
        _validate_full_smoke_rank_diagnostic(
            _json_object(payload, label=f"full-smoke rank evidence {position}"),
            rank=position // 2,
            step=(position % 2) + 1,
        )
        rank_hashes.append(rank_hash)

    source_payload = _read_regular(implementation_source_path, max_bytes=_MAX_CONFIG_BYTES)
    source_sha256 = hashlib.sha256(source_payload).hexdigest()
    if source_sha256 != "638caef60503df8f31c550cecf046ec854a0af332230abad01e3a26f8de6ddee":
        raise ValueError("optimizer full-smoke BF16 implementation changed")
    authorization_base = prior.model_dump(mode="json", exclude={"authorization_hash"})
    authorization_base.update(
        {
            "format_id": (
                "verigym_hwe_decision_sft_64k_optimizer_full_smoke_bf16_tolerance_"
                "replay_authorization_v1"
            ),
            "status": "authorized_for_full_eight_step_bf16_tolerance_replay",
            "authorization_basis": (
                "explicit_user_instruction_authorize_attempt_7_and_standing_same_scope_"
                "authorization"
            ),
            "authorization_scope": (
                "single_preregistered_eight_step_optimizer_smoke_bf16_tolerance"
            ),
            "attempt": 7,
            "replaces_authorization_hash": prior.authorization_hash,
            "prior_full_smoke_authorization_sha256": hashlib.sha256(prior_payload).hexdigest(),
            "prior_full_smoke_failure_report_sha256": hashlib.sha256(failure_payload).hexdigest(),
            "prior_full_smoke_optimizer_steps_confirmed": 2,
            "prior_full_smoke_failure_step": 2,
            "prior_full_smoke_failure_record_index": 76,
            "prior_full_smoke_failure_token_count": 10_693,
            "prior_full_smoke_failed_invariant": "post_clip_global_norm_within_limit",
            "prior_full_smoke_rank_diagnostic_sha256": rank_hashes,
            "gradient_clip_target": 1.0,
            "bfloat16_epsilon": 0.0078125,
            "tolerance_multiplier": 2,
            "post_clip_global_norm_relative_tolerance": 0.015625,
            "post_clip_global_norm_acceptance_lte": 1.015625,
            "tolerance_basis": "two_bfloat16_eps_relative_rounding_margin",
            "tolerance_inherited_from_prior_authorized_schedule": True,
            "tolerance_tuned_to_observed_value": False,
            "implementation_fix": "full_smoke_inherits_validated_bf16_clip_tolerance",
            "implementation_source_sha256": source_sha256,
        }
    )
    return HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization.model_validate(
        {
            **authorization_base,
            "authorization_hash": content_hash(authorization_base),
        }
    )


def validate_optimizer_full_smoke_bf16_tolerance_replay_authorization(
    authorization: HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    **kwargs: Any,
) -> None:
    """Reject attempt 7 or any exact attempt-6 evidence drift."""

    expected = create_optimizer_full_smoke_bf16_tolerance_replay_authorization(**kwargs)
    if authorization != expected:
        raise ValueError("optimizer full-smoke BF16 authorization differs from evidence")


def create_checkpoint_resume_qualification_authorization(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    *,
    dataset_root: Path,
    qualification_root: Path,
    config_path: Path,
    preregistration_receipt_path: Path,
    prior_attempt_7_authorization_path: Path,
    prior_attempt_7_pass_report_path: Path,
    prior_attempt_7_summary_path: Path,
    prior_attempt_7_rank_diagnostic_paths: tuple[Path, ...],
    implementation_source_path: Path,
) -> HweDecisionSft64kCheckpointResumeQualificationAuthorization:
    """Seal attempt 8 against the exact passing attempt-7 execution evidence."""

    expected_receipt = validate_optimizer_smoke_preregistration(
        preregistration,
        dataset_root=dataset_root,
        qualification_root=qualification_root,
        config_path=config_path,
    )
    receipt_payload = _read_regular(preregistration_receipt_path, max_bytes=_MAX_CONFIG_BYTES)
    if _json_object(receipt_payload, label="preregistration receipt") != expected_receipt:
        raise ValueError("checkpoint/resume preregistration receipt changed")

    prior_payload = _read_regular(
        prior_attempt_7_authorization_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    prior = load_optimizer_smoke_execution_authorization(prior_attempt_7_authorization_path)
    if type(prior) is not HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization:
        raise ValueError("checkpoint/resume qualification requires attempt-7 authorization")
    if (
        prior.authorization_hash != ATTEMPT_7_AUTHORIZATION_HASH
        or hashlib.sha256(prior_payload).hexdigest() != ATTEMPT_7_AUTHORIZATION_SHA256
    ):
        raise ValueError("checkpoint/resume attempt-7 authorization changed")

    pass_report_payload = _read_regular(
        prior_attempt_7_pass_report_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    if hashlib.sha256(pass_report_payload).hexdigest() != ATTEMPT_7_PASS_REPORT_SHA256:
        raise ValueError("checkpoint/resume attempt-7 pass report changed")
    _validate_attempt_7_pass_report(
        _json_object(pass_report_payload, label="attempt-7 pass report"),
        authorization=prior,
        preregistration=preregistration,
    )

    summary_payload = _read_regular(prior_attempt_7_summary_path, max_bytes=_MAX_CONFIG_BYTES)
    if hashlib.sha256(summary_payload).hexdigest() != ATTEMPT_7_SUMMARY_SHA256:
        raise ValueError("checkpoint/resume attempt-7 summary changed")
    summary = _json_object(summary_payload, label="attempt-7 summary")
    if (
        summary.get("status") != "passed"
        or summary.get("authorization_hash") != prior.authorization_hash
        or summary.get("optimizer_steps") != 8
        or summary.get("post_step_invariants_passed") != 288
        or summary.get("checkpoint_written") is not False
        or summary.get("adapter_written") is not False
    ):
        raise ValueError("checkpoint/resume attempt-7 summary semantics changed")

    if len(prior_attempt_7_rank_diagnostic_paths) != 32:
        raise ValueError("checkpoint/resume requires all 32 attempt-7 rank diagnostics")
    rank_hashes: list[str] = []
    for position, path in enumerate(prior_attempt_7_rank_diagnostic_paths):
        payload = _read_regular(path, max_bytes=_MAX_CONFIG_BYTES)
        observed_hash = hashlib.sha256(payload).hexdigest()
        if observed_hash != ATTEMPT_7_RANK_DIAGNOSTIC_SHA256[position]:
            raise ValueError(f"checkpoint/resume attempt-7 rank evidence {position} changed")
        rank = position // 8
        step = (position % 8) + 1
        _validate_attempt_7_rank_diagnostic(
            _json_object(payload, label=f"attempt-7 rank {rank} step {step} diagnostic"),
            rank=rank,
            step=step,
            preregistration=preregistration,
        )
        rank_hashes.append(observed_hash)

    implementation_payload = _read_regular(
        implementation_source_path,
        max_bytes=_MAX_CONFIG_BYTES,
    )
    authorization_base = prior.model_dump(mode="json", exclude={"authorization_hash"})
    authorization_base.update(
        {
            "format_id": (
                "verigym_hwe_decision_sft_64k_checkpoint_resume_qualification_authorization_v1"
            ),
            "status": "authorized_for_single_checkpoint_resume_qualification",
            "authorization_basis": (
                "explicit_user_instruction_authorize_checkpoint_resume_qualification"
            ),
            "authorization_scope": (
                "single_four_step_control_vs_two_plus_resume_plus_two_qualification"
            ),
            "attempt": 8,
            "replaces_authorization_hash": prior.authorization_hash,
            "checkpoint_allowed": True,
            "prior_attempt_7_authorization_sha256": hashlib.sha256(prior_payload).hexdigest(),
            "prior_attempt_7_pass_report_sha256": hashlib.sha256(pass_report_payload).hexdigest(),
            "prior_attempt_7_summary_sha256": hashlib.sha256(summary_payload).hexdigest(),
            "prior_attempt_7_optimizer_steps_confirmed": 8,
            "prior_attempt_7_invariants_all_passed": True,
            "prior_attempt_7_rank_diagnostic_sha256": rank_hashes,
            "control_optimizer_steps": 4,
            "checkpoint_producer_optimizer_steps": 2,
            "resumed_optimizer_steps": 2,
            "checkpoint_global_step": 2,
            "checkpoint_count_allowed": 1,
            "checkpoint_save_contents": ["model", "optimizer", "extra"],
            "checkpoint_load_contents": ["model", "optimizer", "extra"],
            "checkpoint_format": "verl_fsdp2_sharded_v0_8",
            "dataloader_state_required": True,
            "explicit_schedule_cursor_required": True,
            "rng_state_required": True,
            "lr_scheduler_state_required": True,
            "exact_resume_equivalence_required": True,
            "temporary_checkpoint_deletion_after_validation_allowed": True,
            "checkpoint_resume_implementation": (
                "three_fresh_torchrun_branches_with_hash_bound_fsdp2_checkpoint"
            ),
            "checkpoint_resume_implementation_source_sha256": hashlib.sha256(
                implementation_payload
            ).hexdigest(),
        }
    )
    return HweDecisionSft64kCheckpointResumeQualificationAuthorization.model_validate(
        {
            **authorization_base,
            "authorization_hash": content_hash(authorization_base),
        }
    )


def validate_checkpoint_resume_qualification_authorization(
    authorization: HweDecisionSft64kCheckpointResumeQualificationAuthorization,
    **kwargs: Any,
) -> None:
    """Reject attempt-8 authorization or any exact attempt-7 evidence drift."""

    expected = create_checkpoint_resume_qualification_authorization(**kwargs)
    if authorization != expected:
        raise ValueError("checkpoint/resume authorization differs from evidence")


def _validate_attempt_7_pass_report(
    report: dict[str, Any],
    *,
    authorization: HweDecisionSft64kOptimizerFullSmokeBf16ToleranceReplayAuthorization,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
) -> None:
    expected = {
        "format_id": "verigym_hwe_decision_sft_64k_optimizer_smoke_execution_v1",
        "status": "passed",
        "authorization_attempt": 7,
        "authorization_hash": authorization.authorization_hash,
        "loader_ready": True,
        "loader_rows_validated": 83,
        "exact_receipts_revalidated": 83,
        "over_32768_rows_validated": 19,
        "max_token_count": 50_117,
        "optimizer_steps_authorized": 8,
        "optimizer_steps": 8,
        "optimizer_state_steps_final": [8],
        "bf16_tolerance_replay": True,
        "post_clip_global_norm_relative_tolerance": 0.015625,
        "post_clip_global_norm_acceptance_lte": 1.015625,
        "checkpoint_written": False,
        "adapter_written": False,
        "development_training_ready": True,
        "production_training_ready": False,
        "new_hpc_jobs_submitted": False,
        "allocation_released": False,
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("checkpoint/resume attempt-7 pass report semantics changed")
    steps = report.get("step_results")
    if not isinstance(steps, list) or len(steps) != 8:
        raise ValueError("checkpoint/resume attempt-7 step results changed")
    for scheduled, result in zip(preregistration.schedule, steps, strict=True):
        if (
            result.get("step") != scheduled.step
            or result.get("source_v4_record_index") != scheduled.source_v4_record_index
            or result.get("source_v4_record_hash") != scheduled.source_v4_record_hash
            or result.get("token_count") != scheduled.token_count
        ):
            raise ValueError("checkpoint/resume attempt-7 scheduled result changed")
        ranks = result.get("rank_results")
        if not isinstance(ranks, list) or len(ranks) != 4:
            raise ValueError("checkpoint/resume attempt-7 rank results changed")
        for rank, rank_result in enumerate(ranks):
            invariants = rank_result.get("post_step_invariants")
            if (
                rank_result.get("rank") != rank
                or rank_result.get("optimizer_steps_observed") != scheduled.step
                or rank_result.get("optimizer_state_steps") != [scheduled.step]
                or rank_result.get("losses_finite_positive") is not True
                or not isinstance(invariants, dict)
                or len(invariants) != 9
                or not all(value is True for value in invariants.values())
            ):
                raise ValueError("checkpoint/resume attempt-7 rank invariant changed")


def _validate_attempt_7_rank_diagnostic(
    diagnostic: dict[str, Any],
    *,
    rank: int,
    step: int,
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
) -> None:
    scheduled = preregistration.schedule[step - 1]
    invariants = diagnostic.get("invariants")
    observed = diagnostic.get("observed")
    if (
        diagnostic.get("format_id") != "verigym_hwe_optimizer_smoke_post_step_diagnostics_v1"
        or diagnostic.get("rank") != rank
        or diagnostic.get("step") != step
        or diagnostic.get("source_v4_record_index") != scheduled.source_v4_record_index
        or diagnostic.get("source_v4_record_hash") != scheduled.source_v4_record_hash
        or diagnostic.get("token_count") != scheduled.token_count
        or diagnostic.get("all_local_invariants_passed") is not True
        or diagnostic.get("all_ranks_invariants_passed") is not True
        or diagnostic.get("failed_local_invariants") != []
        or not isinstance(invariants, dict)
        or len(invariants) != 9
        or not all(value is True for value in invariants.values())
        or not isinstance(observed, dict)
        or observed.get("optimizer_steps") != step
        or observed.get("optimizer_state_steps") != [step]
        or observed.get("post_clip_global_norm_relative_tolerance") != 0.015625
        or observed.get("post_clip_global_norm_acceptance_limit") != 1.015625
    ):
        raise ValueError("checkpoint/resume attempt-7 rank diagnostic semantics changed")


def _validate_full_smoke_bf16_tolerance_failure(
    failure: dict[str, Any],
    *,
    authorization: HweDecisionSft64kOptimizerFullSmokeReplayAuthorization,
) -> None:
    expected = {
        "format_id": "verigym_hwe_decision_sft_64k_optimizer_smoke_execution_v1",
        "status": "failed_closed",
        "scope": "development_optimizer_numerical_smoke_only",
        "authorization_hash": authorization.authorization_hash,
        "authorization_format_id": authorization.format_id,
        "authorization_attempt": 6,
        "replaces_authorization_hash": authorization.replaces_authorization_hash,
        "training_started": True,
        "optimizer_steps_authorized": 8,
        "optimizer_steps_observed_min": 2,
        "optimizer_steps_observed_max": 2,
        "optimizer_steps_confirmed_exact": True,
        "post_step_diagnostics_complete": True,
        "failed_post_step_invariants": ["post_clip_global_norm_within_limit"],
        "bf16_tolerance_replay": False,
        "gradient_clip_target": 1.0,
        "post_clip_global_norm_relative_tolerance": 0.0,
        "post_clip_global_norm_acceptance_lte": 1.0,
        "checkpoint_written": False,
        "adapter_written": False,
        "development_training_ready": False,
        "production_training_ready": False,
        "new_hpc_jobs_submitted": False,
        "allocation_released": False,
        "torchrun_returncode": 1,
    }
    if any(failure.get(key) != value for key, value in expected.items()):
        raise ValueError("optimizer full-smoke BF16 prior failure identity changed")
    first_error = failure.get("first_error")
    if (
        not isinstance(first_error, dict)
        or first_error.get("rank") != 0
        or first_error.get("error_type") != "RuntimeError"
        or first_error.get("error_message")
        != "optimizer smoke step 2 failed its post-step invariants"
        or first_error.get("optimizer_steps_observed") != 2
    ):
        raise ValueError("optimizer full-smoke BF16 first error changed")
    _validate_full_smoke_rank_diagnostic(
        first_error.get("post_step_diagnostics"),
        rank=0,
        step=2,
    )
    rank_failures = failure.get("rank_failures")
    report_diagnostics = failure.get("post_step_diagnostics_by_rank")
    if (
        not isinstance(rank_failures, list)
        or len(rank_failures) != 4
        or not isinstance(report_diagnostics, list)
        or len(report_diagnostics) != 4
    ):
        raise ValueError("optimizer full-smoke BF16 four-rank failure evidence changed")
    for rank, item in enumerate(rank_failures):
        if (
            not isinstance(item, dict)
            or item.get("rank") != rank
            or item.get("error_type") != "RuntimeError"
            or item.get("error_message") != "optimizer smoke step 2 failed its post-step invariants"
            or item.get("optimizer_steps_observed") != 2
        ):
            raise ValueError(f"optimizer full-smoke BF16 rank {rank} failure changed")
        _validate_full_smoke_rank_diagnostic(
            item.get("post_step_diagnostics"),
            rank=rank,
            step=2,
        )
        _validate_full_smoke_rank_diagnostic(
            report_diagnostics[rank],
            rank=rank,
            step=2,
        )


def _validate_full_smoke_rank_diagnostic(
    diagnostic: Any,
    *,
    rank: int,
    step: int,
) -> None:
    if not isinstance(diagnostic, dict):
        raise ValueError(f"optimizer full-smoke BF16 rank {rank} step {step} evidence missing")
    expected_step = {
        1: {
            "source_v4_record_index": 62,
            "source_v4_record_hash": (
                "432d9069ef7793e90ec80e85b1d39e7c61dbdf2e751e5cb5948f58658fffcd03"
            ),
            "token_count": 1_883,
            "engine_pre_clip_global_norm": 4.25,
            "post_clip_global_norm": 0.997597088045443,
            "passed": True,
        },
        2: {
            "source_v4_record_index": 76,
            "source_v4_record_hash": (
                "5980ff5269c3fd0f4ac62cf9cc5775fa2a6e84687407b55844ebe2310436a54b"
            ),
            "token_count": 10_693,
            "engine_pre_clip_global_norm": 3.015625,
            "post_clip_global_norm": 1.0049930877247288,
            "passed": False,
        },
    }
    try:
        expected = expected_step[step]
    except KeyError as exc:
        raise ValueError("optimizer full-smoke BF16 evidence step is invalid") from exc
    passed = bool(expected["passed"])
    expected_invariants = {
        "engine_pre_clip_norm_finite",
        "engine_pre_clip_norm_positive",
        "optimizer_state_parameter_count_matches_gradient_count",
        "optimizer_state_step_matches",
        "optimizer_step_count_matches",
        "post_clip_global_norm_within_limit",
        "post_clip_gradients_finite",
        "post_clip_gradients_nonzero_on_every_rank",
        "trainable_parameter_hash_changed",
    }
    invariants = diagnostic.get("invariants")
    observed = diagnostic.get("observed")
    gradients = observed.get("post_clip_gradients") if isinstance(observed, dict) else None
    if (
        diagnostic.get("format_id") != "verigym_hwe_optimizer_smoke_post_step_diagnostics_v1"
        or diagnostic.get("rank") != rank
        or diagnostic.get("step") != step
        or diagnostic.get("source_v4_record_index") != expected["source_v4_record_index"]
        or diagnostic.get("source_v4_record_hash") != expected["source_v4_record_hash"]
        or diagnostic.get("token_count") != expected["token_count"]
        or diagnostic.get("all_local_invariants_passed") is not passed
        or diagnostic.get("all_ranks_invariants_passed") is not passed
        or diagnostic.get("failed_local_invariants")
        != ([] if passed else ["post_clip_global_norm_within_limit"])
        or not isinstance(invariants, dict)
        or set(invariants) != expected_invariants
        or invariants.get("post_clip_global_norm_within_limit") is not passed
        or any(
            value is not True
            for name, value in invariants.items()
            if name != "post_clip_global_norm_within_limit"
        )
        or not isinstance(observed, dict)
        or not isinstance(gradients, dict)
        or observed.get("optimizer_steps") != step
        or observed.get("engine_pre_clip_global_norm") != expected["engine_pre_clip_global_norm"]
        or observed.get("optimizer_state_steps") != [step]
        or observed.get("optimizer_state_parameter_count") != 496
        or observed.get("gradient_tensor_count") != 496
        or observed.get("post_clip_global_norm_target") != 1.0
        or observed.get("post_clip_global_norm_relative_tolerance") != 0.0
        or observed.get("post_clip_global_norm_acceptance_limit") != 1.0
        or gradients.get("finite") is not True
        or gradients.get("global_norm") != expected["post_clip_global_norm"]
        or gradients.get("global_tensor_count") != 1_984
        or gradients.get("local_tensor_count") != 496
        or gradients.get("nonzero_on_every_rank") is not True
    ):
        raise ValueError(f"optimizer full-smoke BF16 rank {rank} step {step} evidence changed")
    before = observed.get("parameter_hash_before")
    after = observed.get("parameter_hash_after")
    if (
        not isinstance(before, str)
        or not isinstance(after, str)
        or len(before) != 64
        or len(after) != 64
        or any(character not in "0123456789abcdef" for character in before + after)
        or before == after
    ):
        raise ValueError(
            f"optimizer full-smoke BF16 rank {rank} step {step} parameter evidence changed"
        )


def _validate_zero_step_implementation_failure(
    failure: dict[str, Any],
    *,
    authorization: HweDecisionSft64kOptimizerSmokeExecutionAuthorization,
) -> None:
    expected = {
        "status": "failed_closed",
        "authorization_hash": authorization.authorization_hash,
        "training_started": False,
        "optimizer_steps_observed_min": 0,
        "optimizer_steps_observed_max": 0,
        "optimizer_steps_confirmed_exact": True,
        "checkpoint_written": False,
        "adapter_written": False,
        "production_training_ready": False,
        "new_hpc_jobs_submitted": False,
        "allocation_released": False,
        "torchrun_returncode": 1,
    }
    if any(failure.get(key) != value for key, value in expected.items()):
        raise ValueError("optimizer smoke retry requires an exact zero-step failure report")
    first_error = failure.get("first_error")
    if not isinstance(first_error, dict) or (
        first_error.get("error_type") != "AttributeError"
        or first_error.get("error_message") != "'Tensor' object has no attribute 'maximum_'"
        or first_error.get("optimizer_steps_observed") != 0
    ):
        raise ValueError(
            "optimizer smoke retry prior failure is not the registered implementation bug"
        )
    rank_failures = failure.get("rank_failures")
    if (
        not isinstance(rank_failures, list)
        or len(rank_failures) != 4
        or {item.get("rank") for item in rank_failures if isinstance(item, dict)} != set(range(4))
        or any(
            not isinstance(item, dict)
            or item.get("error_type") != "AttributeError"
            or item.get("optimizer_steps_observed") != 0
            for item in rank_failures
        )
    ):
        raise ValueError("optimizer smoke retry requires matching zero-step failures on four ranks")


def _validate_one_step_post_invariant_failure(
    failure: dict[str, Any],
    *,
    authorization: HweDecisionSft64kOptimizerSmokeExecutionRetryAuthorization,
) -> None:
    expected = {
        "format_id": "verigym_hwe_decision_sft_64k_optimizer_smoke_execution_v1",
        "status": "failed_closed",
        "authorization_hash": authorization.authorization_hash,
        "authorization_format_id": authorization.format_id,
        "authorization_attempt": 2,
        "replaces_authorization_hash": authorization.replaces_authorization_hash,
        "training_started": True,
        "optimizer_steps_observed_min": 1,
        "optimizer_steps_observed_max": 1,
        "optimizer_steps_confirmed_exact": True,
        "checkpoint_written": False,
        "adapter_written": False,
        "production_training_ready": False,
        "new_hpc_jobs_submitted": False,
        "allocation_released": False,
        "torchrun_returncode": 1,
    }
    if any(failure.get(key) != value for key, value in expected.items()):
        raise ValueError("optimizer diagnostic requires the exact one-step retry failure")
    first_error = failure.get("first_error")
    if not isinstance(first_error, dict) or (
        first_error.get("error_type") != "RuntimeError"
        or first_error.get("error_message")
        != "optimizer smoke step 1 failed its post-step invariants"
        or first_error.get("optimizer_steps_observed") != 1
    ):
        raise ValueError("optimizer diagnostic retry did not fail at the registered invariant")
    rank_failures = failure.get("rank_failures")
    if (
        not isinstance(rank_failures, list)
        or len(rank_failures) != 4
        or {item.get("rank") for item in rank_failures if isinstance(item, dict)} != set(range(4))
        or any(
            not isinstance(item, dict)
            or item.get("error_type") != "RuntimeError"
            or item.get("error_message") != "optimizer smoke step 1 failed its post-step invariants"
            or item.get("optimizer_steps_observed") != 1
            for item in rank_failures
        )
    ):
        raise ValueError("optimizer diagnostic requires matching one-step failures on four ranks")


def _validate_diagnostic_rounding_failure(
    failure: dict[str, Any],
    *,
    authorization: HweDecisionSft64kOptimizerDiagnosticReplayAuthorization,
) -> None:
    expected = {
        "format_id": "verigym_hwe_decision_sft_64k_optimizer_diagnostic_replay_execution_v1",
        "status": "failed_closed",
        "scope": "single_record_single_optimizer_step_diagnostic",
        "diagnostic_replay": True,
        "diagnostic_replay_passed": False,
        "authorization_hash": authorization.authorization_hash,
        "authorization_attempt": 3,
        "training_started": True,
        "optimizer_steps_observed_min": 1,
        "optimizer_steps_observed_max": 1,
        "optimizer_steps_confirmed_exact": True,
        "checkpoint_written": False,
        "adapter_written": False,
        "development_training_ready": False,
        "production_training_ready": False,
        "new_hpc_jobs_submitted": False,
        "allocation_released": False,
        "torchrun_returncode": 1,
        "post_step_diagnostics_complete": True,
        "failed_post_step_invariants": ["post_clip_global_norm_within_limit"],
    }
    if any(failure.get(key) != value for key, value in expected.items()):
        raise ValueError("optimizer BF16 replay requires the exact diagnostic failure")
    diagnostics = failure.get("post_step_diagnostics_by_rank")
    if not isinstance(diagnostics, list) or len(diagnostics) != 4:
        raise ValueError("optimizer BF16 replay requires four diagnostic snapshots")
    for rank, diagnostic in enumerate(diagnostics):
        invariants = diagnostic.get("invariants") if isinstance(diagnostic, dict) else None
        observed = diagnostic.get("observed") if isinstance(diagnostic, dict) else None
        gradients = observed.get("post_clip_gradients") if isinstance(observed, dict) else None
        if (
            not isinstance(invariants, dict)
            or not isinstance(observed, dict)
            or not isinstance(gradients, dict)
            or diagnostic.get("rank") != rank
            or {name for name, passed in invariants.items() if passed is False}
            != {"post_clip_global_norm_within_limit"}
            or any(not isinstance(passed, bool) for passed in invariants.values())
            or observed.get("post_clip_global_norm_limit") != 1.0
            or gradients.get("global_norm") != 1.0015633596301037
        ):
            raise ValueError("optimizer BF16 replay diagnostic invariant evidence changed")


def _validate_bf16_authorized_schedule_failure(
    failure: dict[str, Any],
    *,
    authorization: HweDecisionSft64kOptimizerBf16ToleranceReplayAuthorization,
) -> None:
    expected = {
        "format_id": ("verigym_hwe_decision_sft_64k_optimizer_bf16_tolerance_replay_execution_v1"),
        "status": "failed_closed",
        "scope": "single_record_single_optimizer_step_bf16_tolerance",
        "diagnostic_replay": True,
        "diagnostic_replay_passed": False,
        "bf16_tolerance_replay": True,
        "authorization_hash": authorization.authorization_hash,
        "authorization_format_id": authorization.format_id,
        "authorization_attempt": 4,
        "optimizer_steps_authorized": 1,
        "training_started": True,
        "optimizer_steps_observed_min": 1,
        "optimizer_steps_observed_max": 1,
        "optimizer_steps_confirmed_exact": True,
        "checkpoint_written": False,
        "adapter_written": False,
        "development_training_ready": False,
        "production_training_ready": False,
        "new_hpc_jobs_submitted": False,
        "allocation_released": False,
        "torchrun_returncode": 1,
        "failed_post_step_invariants": [],
        "gradient_clip_target": 1.0,
        "post_clip_global_norm_relative_tolerance": 0.015625,
        "post_clip_global_norm_acceptance_lte": 1.015625,
    }
    if any(failure.get(key) != value for key, value in expected.items()):
        raise ValueError("optimizer authorized-schedule replay requires exact attempt-4 report")
    first_error = failure.get("first_error")
    if not isinstance(first_error, dict) or any(
        first_error.get(key) != value
        for key, value in {
            "rank": 0,
            "error_type": "RuntimeError",
            "error_message": "optimizer guard blocked a step beyond its authorization",
            "optimizer_steps_observed": 1,
            "post_step_diagnostics": None,
        }.items()
    ):
        raise ValueError("optimizer authorized-schedule attempt-4 guard failure changed")
    rank_failures = failure.get("rank_failures")
    if (
        not isinstance(rank_failures, list)
        or len(rank_failures) != 4
        or any(
            not isinstance(item, dict)
            or item.get("rank") != rank
            or item.get("error_type") != "RuntimeError"
            or item.get("error_message")
            != "optimizer guard blocked a step beyond its authorization"
            or item.get("optimizer_steps_observed") != 1
            or item.get("post_step_diagnostics") is not None
            for rank, item in enumerate(rank_failures)
        )
    ):
        raise ValueError("optimizer authorized-schedule four-rank guard evidence changed")


def _validate_bf16_passing_rank_diagnostic(
    diagnostic: dict[str, Any],
    *,
    rank: int,
) -> None:
    invariants = diagnostic.get("invariants")
    observed = diagnostic.get("observed")
    gradients = observed.get("post_clip_gradients") if isinstance(observed, dict) else None
    expected_invariants = {
        "engine_pre_clip_norm_finite",
        "engine_pre_clip_norm_positive",
        "optimizer_state_parameter_count_matches_gradient_count",
        "optimizer_state_step_matches",
        "optimizer_step_count_matches",
        "post_clip_global_norm_within_limit",
        "post_clip_gradients_finite",
        "post_clip_gradients_nonzero_on_every_rank",
        "trainable_parameter_hash_changed",
    }
    expected_identity = {
        "format_id": "verigym_hwe_optimizer_smoke_post_step_diagnostics_v1",
        "rank": rank,
        "step": 1,
        "source_v4_record_index": 62,
        "source_v4_record_hash": (
            "432d9069ef7793e90ec80e85b1d39e7c61dbdf2e751e5cb5948f58658fffcd03"
        ),
        "token_count": 1_883,
        "all_local_invariants_passed": True,
        "all_ranks_invariants_passed": True,
        "failed_local_invariants": [],
    }
    if any(diagnostic.get(key) != value for key, value in expected_identity.items()):
        raise ValueError(f"optimizer authorized-schedule rank {rank} identity changed")
    if (
        not isinstance(invariants, dict)
        or set(invariants) != expected_invariants
        or not all(value is True for value in invariants.values())
        or not isinstance(observed, dict)
        or not isinstance(gradients, dict)
        or observed.get("optimizer_steps") != 1
        or observed.get("engine_pre_clip_global_norm") != 4.1875
        or observed.get("optimizer_state_steps") != [1]
        or observed.get("optimizer_state_parameter_count") != 496
        or observed.get("gradient_tensor_count") != 496
        or observed.get("post_clip_global_norm_target") != 1.0
        or observed.get("post_clip_global_norm_relative_tolerance") != 0.015625
        or observed.get("post_clip_global_norm_acceptance_limit") != 1.015625
        or gradients.get("finite") is not True
        or gradients.get("global_norm") != 0.9985010900168197
        or gradients.get("global_tensor_count") != 1_984
        or gradients.get("local_tensor_count") != 496
        or gradients.get("nonzero_on_every_rank") is not True
    ):
        raise ValueError(f"optimizer authorized-schedule rank {rank} invariants changed")
    before = observed.get("parameter_hash_before")
    after = observed.get("parameter_hash_after")
    if (
        not isinstance(before, str)
        or not isinstance(after, str)
        or len(before) != 64
        or len(after) != 64
        or any(character not in "0123456789abcdef" for character in before + after)
        or before == after
    ):
        raise ValueError(f"optimizer authorized-schedule rank {rank} parameter evidence changed")


def _validate_authorized_schedule_pass_report(
    report: dict[str, Any],
    *,
    authorization: HweDecisionSft64kOptimizerAuthorizedScheduleReplayAuthorization,
) -> None:
    expected = {
        "format_id": (
            "verigym_hwe_decision_sft_64k_optimizer_authorized_schedule_replay_execution_v1"
        ),
        "status": "passed",
        "scope": "single_record_single_optimizer_step_authorized_schedule",
        "authorization_hash": authorization.authorization_hash,
        "authorization_format_id": authorization.format_id,
        "authorization_attempt": 5,
        "optimizer_steps_authorized": 1,
        "optimizer_step_guard_limit": 1,
        "loader_rows_validated": 83,
        "exact_receipts_revalidated": 83,
        "over_32768_rows_validated": 19,
        "max_token_count": 50_117,
        "optimizer_steps": 1,
        "trainable_parameter_hash_changed": True,
        "optimizer_state_steps_final": [1],
        "checkpoint_written": False,
        "adapter_written": False,
        "development_training_ready": False,
        "production_training_ready": False,
        "new_hpc_jobs_submitted": False,
        "existing_allocation_modified": False,
        "allocation_released": False,
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("optimizer full smoke requires the exact attempt-5 pass report")
    step_results = report.get("step_results")
    if not isinstance(step_results, list) or len(step_results) != 1:
        raise ValueError("optimizer full smoke prior report must contain exactly one step")
    step = step_results[0]
    rank_results = step.get("rank_results") if isinstance(step, dict) else None
    if (
        not isinstance(step, dict)
        or step.get("step") != 1
        or step.get("source_v4_record_index") != 62
        or step.get("source_v4_record_hash")
        != "432d9069ef7793e90ec80e85b1d39e7c61dbdf2e751e5cb5948f58658fffcd03"
        or step.get("token_count") != 1_883
        or not isinstance(rank_results, list)
        or len(rank_results) != 4
    ):
        raise ValueError("optimizer full smoke prior step identity changed")
    for rank, result in enumerate(rank_results):
        invariants = result.get("post_step_invariants") if isinstance(result, dict) else None
        post_clip = result.get("post_clip_gradients") if isinstance(result, dict) else None
        if (
            not isinstance(result, dict)
            or not isinstance(invariants, dict)
            or len(invariants) != 9
            or not all(value is True for value in invariants.values())
            or not isinstance(post_clip, dict)
            or result.get("rank") != rank
            or result.get("loss_values") != [0.24095161259174347]
            or result.get("losses_finite_positive") is not True
            or result.get("engine_pre_clip_global_norm") != 4.46875
            or post_clip.get("global_norm") != 1.000200274516193
            or result.get("parameter_hash_changed") is not True
            or result.get("optimizer_state_steps") != [1]
            or result.get("optimizer_state_parameter_count") != 496
            or result.get("optimizer_steps_observed") != 1
        ):
            raise ValueError(f"optimizer full smoke prior rank {rank} result changed")


def _validate_authorized_schedule_passing_rank_diagnostic(
    diagnostic: dict[str, Any],
    *,
    rank: int,
) -> None:
    invariants = diagnostic.get("invariants")
    observed = diagnostic.get("observed")
    gradients = observed.get("post_clip_gradients") if isinstance(observed, dict) else None
    if (
        diagnostic.get("format_id") != "verigym_hwe_optimizer_smoke_post_step_diagnostics_v1"
        or diagnostic.get("rank") != rank
        or diagnostic.get("step") != 1
        or diagnostic.get("source_v4_record_index") != 62
        or diagnostic.get("source_v4_record_hash")
        != "432d9069ef7793e90ec80e85b1d39e7c61dbdf2e751e5cb5948f58658fffcd03"
        or diagnostic.get("token_count") != 1_883
        or diagnostic.get("all_local_invariants_passed") is not True
        or diagnostic.get("all_ranks_invariants_passed") is not True
        or diagnostic.get("failed_local_invariants") != []
        or not isinstance(invariants, dict)
        or len(invariants) != 9
        or not all(value is True for value in invariants.values())
        or not isinstance(observed, dict)
        or not isinstance(gradients, dict)
        or observed.get("optimizer_steps") != 1
        or observed.get("engine_pre_clip_global_norm") != 4.46875
        or observed.get("optimizer_state_steps") != [1]
        or observed.get("optimizer_state_parameter_count") != 496
        or observed.get("gradient_tensor_count") != 496
        or observed.get("post_clip_global_norm_target") != 1.0
        or observed.get("post_clip_global_norm_relative_tolerance") != 0.015625
        or observed.get("post_clip_global_norm_acceptance_limit") != 1.015625
        or gradients.get("finite") is not True
        or gradients.get("global_norm") != 1.000200274516193
        or gradients.get("global_tensor_count") != 1_984
        or gradients.get("local_tensor_count") != 496
        or gradients.get("nonzero_on_every_rank") is not True
    ):
        raise ValueError(f"optimizer full smoke rank {rank} diagnostic changed")


def _validate_schedule(
    preregistration: HweDecisionSft64kOptimizerSmokePreregistration,
    rows: list[HweDeepSeekHarnessDecisionSftExampleV4],
) -> None:
    for scheduled, expected_index in zip(
        preregistration.schedule,
        SCHEDULE_INDICES,
        strict=True,
    ):
        row = rows[expected_index]
        if (
            scheduled.source_v4_record_index != expected_index
            or scheduled.source_v4_record_hash != row.record_hash
            or scheduled.task_id != row.task_id
            or scheduled.token_count != row.token_count
            or scheduled.action_names != row.action_names
        ):
            raise ValueError(f"optimizer smoke schedule row {scheduled.step} differs from v4")
    first_longest = preregistration.schedule[3]
    second_longest = preregistration.schedule[7]
    if first_longest != second_longest.model_copy(update={"step": 4}):
        raise ValueError("optimizer smoke longest-row repetition changed")


def _validate_qualification(summary: dict[str, Any], gpu: dict[str, Any]) -> None:
    expected_summary = {
        "status": "passed",
        "loader_ready": True,
        "gpu_probe_passed": True,
        "development_training_ready": True,
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "adapter_written": False,
        "checkpoint_written": False,
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            raise ValueError(f"optimizer smoke prerequisite summary {key} changed")
    if summary.get("dataset_v4", {}).get("dataset_hash") != V4_DATASET_HASH:
        raise ValueError("optimizer smoke prerequisite summary dataset changed")
    hpc = summary.get("hpc", {})
    if (
        hpc.get("existing_lsf_job_id") != "466876"
        or hpc.get("new_hpc_jobs_submitted") is not False
        or hpc.get("allocation_released") is not False
    ):
        raise ValueError("optimizer smoke prerequisite allocation evidence changed")
    source_v3 = summary.get("source_v3", {})
    if source_v3.get("historical_files_modified") is not False:
        raise ValueError("optimizer smoke prerequisite reports modified v3 history")

    expected_gpu = {
        "status": "passed",
        "loader_ready": True,
        "loader_rows_validated": 83,
        "gpu_probe_passed": True,
        "development_training_ready": True,
        "production_training_ready": False,
        "training_started": False,
        "optimizer_steps": 0,
        "adapter_written": False,
        "checkpoint_written": False,
        "world_size": 4,
        "ulysses_sequence_parallel_size": 4,
        "longest_record_index": 61,
        "longest_record_tokens": 50_117,
        "bounded_fused_vocabulary_head": True,
        "global_shift_labels_used": True,
    }
    for key, expected in expected_gpu.items():
        if gpu.get(key) != expected:
            raise ValueError(f"optimizer smoke prerequisite GPU evidence {key} changed")


def _json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    import json

    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"optimizer smoke {label} must be a JSON object")
    return value


def _safe_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"{label} must be a directory")
    return resolved


def _read_regular(path: Path, *, max_bytes: int) -> bytes:
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"optimizer smoke input is not a regular file: {path.name}")
    if metadata.st_size <= 0 or metadata.st_size > max_bytes:
        raise ValueError(f"optimizer smoke input size is invalid: {path.name}")
    return path.read_bytes()


__all__ = [
    "ATTEMPT_7_AUTHORIZATION_HASH",
    "ATTEMPT_7_AUTHORIZATION_SHA256",
    "ATTEMPT_7_PASS_REPORT_SHA256",
    "ATTEMPT_7_RANK_DIAGNOSTIC_SHA256",
    "ATTEMPT_7_SUMMARY_SHA256",
    "AUTHORIZED_SCHEDULE_AUTHORIZATION_HASH",
    "AUTHORIZED_SCHEDULE_AUTHORIZATION_SHA256",
    "AUTHORIZED_SCHEDULE_PASS_REPORT_SHA256",
    "AUTHORIZED_SCHEDULE_RANK_DIAGNOSTIC_SHA256",
    "BF16_TOLERANCE_AUTHORIZATION_HASH",
    "BF16_TOLERANCE_AUTHORIZATION_SHA256",
    "BF16_TOLERANCE_FAILURE_REPORT_SHA256",
    "BF16_TOLERANCE_RANK_DIAGNOSTIC_SHA256",
    "DIAGNOSTIC_AUTHORIZATION_HASH",
    "DIAGNOSTIC_FAILURE_REPORT_SHA256",
    "GPU_QUALIFICATION_SHA256",
    "FULL_SMOKE_AUTHORIZATION_HASH",
    "FULL_SMOKE_AUTHORIZATION_SHA256",
    "FULL_SMOKE_FAILURE_REPORT_SHA256",
    "FULL_SMOKE_RANK_DIAGNOSTIC_SHA256",
    "ORIGINAL_AUTHORIZATION_HASH",
    "ORIGINAL_FAILURE_REPORT_SHA256",
    "OptimizerSmokeExecutionAuthorization",
    "QUALIFICATION_SUMMARY_SHA256",
    "RETRY_AUTHORIZATION_HASH",
    "RETRY_FAILURE_REPORT_SHA256",
    "SCHEDULE_INDICES",
    "V4_DATASET_HASH",
    "V4_MANIFEST_SHA256",
    "V4_TRAIN_JSONL_SHA256",
    "create_optimizer_bf16_tolerance_replay_authorization",
    "create_checkpoint_resume_qualification_authorization",
    "create_optimizer_authorized_schedule_replay_authorization",
    "create_optimizer_diagnostic_replay_authorization",
    "create_optimizer_full_smoke_replay_authorization",
    "create_optimizer_full_smoke_bf16_tolerance_replay_authorization",
    "create_optimizer_smoke_execution_authorization",
    "create_optimizer_smoke_execution_retry_authorization",
    "load_optimizer_smoke_execution_authorization",
    "load_optimizer_smoke_preregistration",
    "validate_optimizer_diagnostic_replay_authorization",
    "validate_checkpoint_resume_qualification_authorization",
    "validate_optimizer_authorized_schedule_replay_authorization",
    "validate_optimizer_bf16_tolerance_replay_authorization",
    "validate_optimizer_full_smoke_replay_authorization",
    "validate_optimizer_full_smoke_bf16_tolerance_replay_authorization",
    "validate_optimizer_smoke_execution_authorization",
    "validate_optimizer_smoke_execution_retry_authorization",
    "validate_optimizer_smoke_preregistration",
]
