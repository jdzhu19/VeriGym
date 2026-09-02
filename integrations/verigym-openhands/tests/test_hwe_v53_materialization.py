from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

from verigym_openhands.hwe_v53_materialization import (
    OPENHANDS_V53_OPT_IN_ENV,
    V53Stages,
    run_v53_zero_provider,
    validate_v53_authorization,
    validate_v53_canary_contract,
)

_TRAINING_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728"
_VALIDATION_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204"
_V33 = {
    "task_hash": "9322fa0b8455126e5c5f2e68ae02c47484935d5ea84bf69b9e6494658e229e86",
    "source_hash": "15861c5f52071656a4ac8dbe7f96df49c974d24c2e3f53f9e449eba12794f02f",
    "verifier_image": "sha256:459deab1a9b65a25be4583087238308dd12e773b818e720299cc8cafe55f4f64",
    "source_image_lock_file_sha256": (
        "55ff6b4efb9675a0a6d512b32d0b33d7778d93d81159086c7485b9f3ebe92a6b"
    ),
    "source_image_lock_hash": "b3fe6732fe4d9b52a6444cda90b25add311665af537acf6b389ad1fdafa1933b",
    "command_image": "sha256:ed935e093a8f5df4f081ee94d7fb3696335350053dd74fbbd5178b23c2fd1784",
    "lock_file_sha256": "a3a29f4ad2515c9502b3716e8644806154c7f9a74d388f9cd9c741d81458dc22",
    "lock_hash": "4e6bcb561d1c631955dcf9b4a2475a0b09d5bb6bb6b98441cd20101f893400d7",
    "security_scan_file_sha256": (
        "6357976446539e526c15cf22a8e9616df650e4ac30117934898b7a40eb339ed1"
    ),
    "security_scan_id": "55e94ec5fd12482534238867e109f920779685d0ef9f18b0db03e99f88be62cf",
}


def _sealed(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "receipt_hash": content_hash(value)}


def _authorization() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[3]
        / "configs/training/qwen35_hwe_openhands_v53_v23_canary_materialization_v1.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _lock(task_id: str, image: str, *, validation: bool = False) -> dict[str, Any]:
    base: dict[str, Any] = {
        "provider_calls": 0,
        "model_process_count": 0,
        "task_id": task_id,
        "task_hash": "1" * 64,
        "source_hash": "2" * 64,
        "verifier_image": "sha256:" + "3" * 64,
        "command_image": "sha256:" + image * 64,
        "source_image_lock_file_sha256": "8" * 64,
        "source_image_lock_hash": "9" * 64,
        "lock_file_sha256": "a" * 64,
        "lock_hash": "5" * 64,
        "security_scan_file_sha256": "b" * 64,
        "security_scan_id": "6" * 64,
        "scanner_profile_id": "cva6-hwe-command-container-native-offline-v2",
        "security_scan_passed": True,
        "codex_present": False,
        "provider_credentials_present": False,
        "hidden_assets_present": False,
        "build_network": "none",
        "runtime_network": "none",
    }
    if validation:
        base.update(_V33)
        base["source"] = "sealed_v33_revalidated"
    return _sealed(base)


def _stages(order: list[str], *, fail: str | None = None) -> V53Stages:
    def stage(name: str, receipt: dict[str, Any]) -> Callable[[Path], dict[str, Any]]:
        def run(staging: Path) -> dict[str, Any]:
            assert staging.name.startswith(".v53-result.v53-staging-")
            order.append(name)
            value = copy.deepcopy(receipt)
            if name == fail:
                value["provider_calls"] = 1
                base = {key: item for key, item in value.items() if key != "receipt_hash"}
                value["receipt_hash"] = content_hash(base)
            return value

        return run

    transfer = _sealed(
        {
            "provider_calls": 0,
            "model_process_count": 0,
            "task_id": _TRAINING_TASK,
            "verifier_image": "sha256:" + "3" * 64,
            "layer_inventory": [{"digest": "sha256:" + "c" * 64, "size": 123, "cache_hit": False}],
            "temporary_archive_cleanup_count": 1,
            "raw_stderr_persisted": False,
        }
    )
    qualification = _sealed(
        {
            "provider_calls": 0,
            "model_process_count": 0,
            "task_id": _TRAINING_TASK,
            "task_hash": "1" * 64,
            "source_hash": "2" * 64,
            "verifier_image": "sha256:" + "3" * 64,
            "transfer_receipt_hash": transfer["receipt_hash"],
            "infrastructure_valid": True,
            "base_failed": True,
            "reference_passed": True,
            "verifier_network": "none",
        }
    )
    scan = _sealed(
        {
            "provider_calls": 0,
            "model_process_count": 0,
            "task_id": _TRAINING_TASK,
            "task_hash": "1" * 64,
            "source_hash": "2" * 64,
            "verifier_image": "sha256:" + "3" * 64,
            "command_image": "sha256:" + "4" * 64,
            "security_scan_file_sha256": "b" * 64,
            "security_scan_id": "6" * 64,
            "scanner_profile_id": "cva6-hwe-command-container-native-offline-v2",
            "scan_passed": True,
            "codex_present": False,
            "provider_credentials_present": False,
            "hidden_assets_present": False,
            "network_available": False,
        }
    )
    return V53Stages(
        pr2728_image_transfer=stage("pr2728_image_transfer", transfer),
        pr2728_public_qualification=stage("pr2728_public_qualification", qualification),
        pr2728_v2_security_scan=stage("pr2728_v2_security_scan", scan),
        pr2728_command_image_lock=stage("pr2728_command_image_lock", _lock(_TRAINING_TASK, "4")),
        pr3204_v33_lock_revalidation=stage(
            "pr3204_v33_lock_revalidation", _lock(_VALIDATION_TASK, "7", validation=True)
        ),
    )


def test_v53_authorization_binds_the_frozen_v52_failure_and_layer_protocol() -> None:
    authorization = validate_v53_authorization(_authorization())

    assert authorization["predecessor_v52"]["behavior_failure_count"] == 0
    assert authorization["materialization_inputs"]["transfer"]["platform"] == "linux/amd64"
    assert authorization["required_controls"]["per_layer_published_before_next_download"]
    assert authorization["authorized_actions"]["invoke_provider"] is False


def test_v53_atomically_materializes_the_shifted_v54_canary_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENHANDS_V53_OPT_IN_ENV, "1")
    order: list[str] = []
    output = tmp_path / "v53-result"

    result = run_v53_zero_provider(
        authorization=_authorization(),
        stages=_stages(order),
        output=output,
    )

    assert order == [
        "pr2728_image_transfer",
        "pr2728_public_qualification",
        "pr2728_v2_security_scan",
        "pr2728_command_image_lock",
        "pr3204_v33_lock_revalidation",
    ]
    contract = validate_v53_canary_contract(
        json.loads((output / "canary-contract.json").read_text(encoding="utf-8"))
    )
    assert result["status"] == "completed_v23_canary_contract_materialized"
    assert contract["campaign_id"] == "openhands-hwe-v54-v23-provider-canary-v1"
    assert contract["v52_boundary"]["behavior_failure_count"] == 0
    assert contract["teacher"]["provider_hidden_thinking"] == "disabled"
    assert contract["formal_collection_allowed"] is False
    assert not list(tmp_path.glob(".v53-result.v53-staging-*"))


def test_v53_failure_removes_partial_contract_but_keeps_identity_frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENHANDS_V53_OPT_IN_ENV, "1")
    output = tmp_path / "v53-result"

    with pytest.raises(ConfigurationError, match="invoked a provider"):
        run_v53_zero_provider(
            authorization=_authorization(),
            stages=_stages([], fail="pr2728_v2_security_scan"),
            output=output,
        )

    assert output.exists() is False
    assert not list(tmp_path.glob(".v53-result.v53-staging-*"))
