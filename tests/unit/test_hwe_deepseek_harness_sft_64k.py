from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from verigym.hwe.deepseek_harness_sft_64k import (
    V3_DATASET_HASH,
    V3_MANIFEST_SHA256,
    V3_TRAIN_JSONL_SHA256,
    load_frozen_decision_dataset_v3,
)
from verigym.hwe.qwen_action_tokenizer import loss_mask_sha256, token_ids_sha256
from verigym.schemas.hwe import (
    HweDeepSeekHarnessDecisionSftDatasetManifestV4,
    HweDeepSeekHarnessDecisionSftExampleV4,
)

_V3_ROOT = Path(
    "/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/pilot-3task-v3/dataset"
)
_V4_ROOT = Path(
    "/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/decision-sft-64k-v4/dataset"
)


def test_exact_token_hash_formats_are_fixed_width_and_fail_closed() -> None:
    assert token_ids_sha256([1, 256]) != token_ids_sha256([1, 0, 1])
    assert len(token_ids_sha256([0, 0xFFFFFFFF])) == 64
    assert len(loss_mask_sha256([0, 1, 1, 0])) == 64
    with pytest.raises(ValueError, match="unsigned 32-bit"):
        token_ids_sha256([-1])
    with pytest.raises(ValueError, match="zero and one"):
        loss_mask_sha256([0, 2])


@pytest.mark.skipif(
    not (_V3_ROOT / "train.jsonl").is_file() or not (_V4_ROOT / "train.jsonl").is_file(),
    reason="qualified local DeepSeek Harness artifacts are not installed",
)
def test_real_v4_is_an_unchanged_ordered_derivation_of_frozen_v3() -> None:
    source = load_frozen_decision_dataset_v3(_V3_ROOT)
    manifest = HweDeepSeekHarnessDecisionSftDatasetManifestV4.model_validate_json(
        (_V4_ROOT / "dataset-manifest.json").read_bytes()
    )
    rows = [
        HweDeepSeekHarnessDecisionSftExampleV4.model_validate_json(line).model_dump(mode="json")
        for line in (_V4_ROOT / "train.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert source.manifest.dataset_hash == manifest.source_v3_dataset_hash == V3_DATASET_HASH
    assert source.manifest_sha256 == manifest.source_v3_manifest_sha256 == V3_MANIFEST_SHA256
    assert (
        source.train_jsonl_sha256
        == manifest.source_v3_train_jsonl_sha256
        == (V3_TRAIN_JSONL_SHA256)
    )
    assert manifest.record_count == len(rows) == 83
    assert max(row["token_count"] for row in rows) == 50_117
    assert sum(row["token_count"] > 32_768 for row in rows) == 19
    assert all(row["token_count"] <= 65_536 for row in rows)
    assert [row["source_v3_record_hash"] for row in rows] == source.manifest.record_hashes
    for old, new in zip(source.rows, rows, strict=True):
        assert new["tools"] == old["tools"]
        assert new["input_messages"] == old["input_messages"]
        assert new["target_message"] == old["target_message"]
    old_actions = Counter(action for row in source.rows for action in row["action_names"])
    new_actions = Counter(action for row in rows for action in row["action_names"])
    assert old_actions == new_actions


def test_v4_manifest_contains_no_nap_or_training_readiness_claim() -> None:
    if not (_V4_ROOT / "dataset-manifest.json").is_file():
        pytest.skip("qualified local DeepSeek Harness v4 artifact is not installed")
    manifest = json.loads((_V4_ROOT / "dataset-manifest.json").read_text(encoding="utf-8"))
    assert manifest["nap_required"] is False
    assert manifest["production_training_ready"] is False
    assert manifest["training_started"] is False
    assert manifest["hpc_jobs_submitted"] is False
    assert manifest["gpu_hours"] == 0
