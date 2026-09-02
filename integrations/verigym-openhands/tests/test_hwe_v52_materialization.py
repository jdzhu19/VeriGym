from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

from verigym_openhands.hwe_v52_materialization import (
    OPENHANDS_V52_OPT_IN_ENV,
    V52Stages,
    run_v52_zero_provider,
    validate_v52_canary_contract,
)

_TRAINING_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2728"
_VALIDATION_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204"
_V33_PR3204_LOCK = {
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
    "security_scan_file_sha256": "6357976446539e526c15cf22a8e9616df650e4ac30117934898b7a40eb339ed1",
    "security_scan_id": "55e94ec5fd12482534238867e109f920779685d0ef9f18b0db03e99f88be62cf",
}


def _sealed(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "receipt_hash": content_hash(value)}


def _base() -> dict[str, Any]:
    return {"provider_calls": 0, "model_process_count": 0}


def _lock(task_id: str, *, image_byte: str, source: str | None = None) -> dict[str, Any]:
    value = {
        **_base(),
        "task_id": task_id,
        "task_hash": "1" * 64,
        "source_hash": "2" * 64,
        "verifier_image": "sha256:" + "3" * 64,
        "command_image": "sha256:" + image_byte * 64,
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
    if source is not None:
        value["source"] = source
    if task_id == _VALIDATION_TASK:
        value.update(_V33_PR3204_LOCK)
    return _sealed(value)


def _authorization() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[3]
        / "configs/training/qwen35_hwe_openhands_v52_v23_canary_materialization_v1.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _stages(
    order: list[str],
    *,
    invalid_stage: str | None = None,
    drift: tuple[str, str, str] | None = None,
) -> V52Stages:
    def stage(name: str, receipt: dict[str, Any]) -> Callable[[Path], dict[str, Any]]:
        def run(staging: Path) -> dict[str, Any]:
            assert staging.name.startswith(".v52-result.v52-staging-")
            order.append(name)
            value = copy.deepcopy(receipt)
            if name == invalid_stage:
                value["provider_calls"] = 1
            if drift is not None and name == drift[0]:
                value[drift[1]] = drift[2]
            if name == invalid_stage or (drift is not None and name == drift[0]):
                base = {key: item for key, item in value.items() if key != "receipt_hash"}
                value["receipt_hash"] = content_hash(base)
            return value

        return run

    transfer = _sealed(
        {
            **_base(),
            "task_id": _TRAINING_TASK,
            "verifier_image": "sha256:" + "3" * 64,
            "layer_inventory": [
                {
                    "digest": "sha256:" + "c" * 64,
                    "size": 123,
                    "cache_hit": False,
                }
            ],
            "temporary_archive_cleanup_count": 1,
            "raw_stderr_persisted": False,
        }
    )
    return V52Stages(
        pr2728_image_transfer=stage("pr2728_image_transfer", transfer),
        pr2728_public_qualification=stage(
            "pr2728_public_qualification",
            _sealed(
                {
                    **_base(),
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
            ),
        ),
        pr2728_v2_security_scan=stage(
            "pr2728_v2_security_scan",
            _sealed(
                {
                    **_base(),
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
            ),
        ),
        pr2728_command_image_lock=stage(
            "pr2728_command_image_lock",
            _lock(_TRAINING_TASK, image_byte="4"),
        ),
        pr3204_v33_lock_revalidation=stage(
            "pr3204_v33_lock_revalidation",
            _lock(
                _VALIDATION_TASK,
                image_byte="7",
                source="sealed_v33_revalidated",
            ),
        ),
    )


def test_v52_runs_the_exact_zero_provider_order_and_atomically_publishes_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENHANDS_V52_OPT_IN_ENV, "1")
    order: list[str] = []
    output = tmp_path / "v52-result"

    result = run_v52_zero_provider(
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
    assert result["status"] == "completed_v23_canary_contract_materialized"
    assert result["provider_calls"] == 0
    assert result["model_process_count"] == 0
    assert result["canary_executed"] is False
    assert output.is_dir()
    contract = validate_v52_canary_contract(
        json.loads((output / "canary-contract.json").read_text(encoding="utf-8"))
    )
    assert [item["task_id"] for item in contract["schedule"]] == [
        _TRAINING_TASK,
        _VALIDATION_TASK,
    ]
    assert contract["teacher"]["provider_hidden_thinking"] == "disabled"
    assert contract["teacher"]["openhands_sdk_version"] == "1.42.1"
    assert contract["teacher"]["litellm_version"] == "1.93.0"
    assert contract["teacher"]["tiktoken_version"] == "0.7.0"
    assert contract["formal_collection_allowed"] is False
    assert contract["formal_collection_started"] is False
    assert contract["training_started"] is False
    assert not list(tmp_path.glob(".v52-result.v52-staging-*"))


def test_v52_failure_removes_staging_and_publishes_no_partial_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENHANDS_V52_OPT_IN_ENV, "1")
    order: list[str] = []
    output = tmp_path / "v52-result"

    with pytest.raises(ConfigurationError, match="invoked a provider"):
        run_v52_zero_provider(
            authorization=_authorization(),
            stages=_stages(order, invalid_stage="pr2728_v2_security_scan"),
            output=output,
        )

    assert order == [
        "pr2728_image_transfer",
        "pr2728_public_qualification",
        "pr2728_v2_security_scan",
    ]
    assert output.exists() is False
    assert not list(tmp_path.glob(".v52-result.v52-staging-*"))


def test_v52_requires_explicit_opt_in_before_any_stage(tmp_path: Path) -> None:
    order: list[str] = []

    with pytest.raises(ConfigurationError, match=f"{OPENHANDS_V52_OPT_IN_ENV}=1"):
        run_v52_zero_provider(
            authorization=_authorization(),
            stages=_stages(order),
            output=tmp_path / "v52-result",
        )

    assert order == []


def test_v52_rejects_authorization_drift_before_any_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENHANDS_V52_OPT_IN_ENV, "1")
    order: list[str] = []
    authorization = _authorization()
    authorization["seed"] = 499

    with pytest.raises(ConfigurationError, match="identity changed"):
        run_v52_zero_provider(
            authorization=authorization,
            stages=_stages(order),
            output=tmp_path / "v52-result",
        )

    assert order == []


@pytest.mark.parametrize(
    ("stage_name", "field", "replacement"),
    [
        ("pr2728_public_qualification", "source_hash", "d" * 64),
        ("pr2728_v2_security_scan", "command_image", "sha256:" + "d" * 64),
    ],
)
def test_v52_rejects_cross_stage_identity_drift_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage_name: str,
    field: str,
    replacement: str,
) -> None:
    monkeypatch.setenv(OPENHANDS_V52_OPT_IN_ENV, "1")
    output = tmp_path / "v52-result"

    with pytest.raises(ConfigurationError, match="stage identities differ"):
        run_v52_zero_provider(
            authorization=_authorization(),
            stages=_stages([], drift=(stage_name, field, replacement)),
            output=output,
        )

    assert output.exists() is False
    assert not list(tmp_path.glob(".v52-result.v52-staging-*"))


def test_v52_rejects_a_well_formed_but_non_v33_pr3204_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPENHANDS_V52_OPT_IN_ENV, "1")
    output = tmp_path / "v52-result"

    with pytest.raises(ConfigurationError, match="v33 lock was not revalidated"):
        run_v52_zero_provider(
            authorization=_authorization(),
            stages=_stages(
                [],
                drift=("pr3204_v33_lock_revalidation", "lock_hash", "d" * 64),
            ),
            output=output,
        )

    assert output.exists() is False
    assert not list(tmp_path.glob(".v52-result.v52-staging-*"))
