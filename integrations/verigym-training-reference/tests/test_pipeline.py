from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.evolution.rewards import REPO_RTL_SPARSE_V1
from verigym.experiments.state import load_json_model, load_jsonl_models
from verigym.schemas.evolution import (
    EpisodeTrajectory,
    RewardDerivationRecord,
    RewardVector,
    TaskSplitEntry,
    TaskSplitManifest,
    TrajectoryDatasetManifest,
    TrajectoryEligibility,
    TrajectoryEvent,
)

from verigym_training_reference import pipeline
from verigym_training_reference.pipeline import (
    inspect_model_snapshot,
    prepare_training_bundle,
    register_checkpoint,
    validate_training_bundle,
)
from verigym_training_reference.reward_oracle import TrainingRewardOracle
from verigym_training_reference.schemas import TrainingReferenceConfig
from verigym_training_reference.trl_adapter import TrlRewardAdapter, build_trl_dataset_rows

HASHES = [f"{index:x}" * 64 for index in range(1, 16)]


def _split() -> TaskSplitManifest:
    training = TaskSplitEntry(
        task_id="fixture/train",
        source_hash=HASHES[0],
        task_hash=HASHES[1],
        license="Apache-2.0",
        attribution="fixture",
    )
    heldout = TaskSplitEntry(
        task_id="fixture/heldout",
        source_hash=HASHES[2],
        task_hash=HASHES[3],
        license="Apache-2.0",
        attribution="fixture",
    )
    base = {
        "schema_version": "1.0",
        "split_id": "training-reference-fixture",
        "training": [training.model_dump(mode="json")],
        "validation": [],
        "heldout": [heldout.model_dump(mode="json")],
        "heldout_assets_loaded_after_version_hash": None,
    }
    return TaskSplitManifest.model_validate({**base, "manifest_hash": content_hash(base)})


def _reward() -> RewardVector:
    return RewardVector(
        outcome_kind="resolved_candidate",
        infrastructure_valid=1,
        policy_compliance=1,
        public_test_reached=1,
        public_test_passed=1,
        patch_reproducible=1,
        candidate_compile_passed=1,
        hidden_regression_passed=1,
        task_resolved=1,
        changed_file_count=1,
        added_lines=4,
        deleted_lines=1,
        public_tool_calls=1,
        wall_time_s=0.5,
        input_tokens=10,
        output_tokens=20,
    )


def _trajectory(split: TaskSplitManifest) -> EpisodeTrajectory:
    reward = _reward()
    event_payload: dict[str, Any] = {
        "schema_version": "1.0",
        "text": "module demo; endmodule\n",
        "original_bytes": 23,
        "original_sha256": HASHES[4],
        "truncated": False,
    }
    event = TrajectoryEvent(
        sequence=0,
        event_type="agent_message",
        content_class="agent_generated",
        payload=event_payload,
        payload_sha256=content_hash(event_payload),
    )
    base = {
        "schema_version": "1.0",
        "trajectory_id": "trajectory:training-reference-run",
        "run_id": "training-reference-run",
        "experiment_id": "training-reference-experiment",
        "plan_item_id": "training-reference-plan",
        "task_id": "fixture/train",
        "task_hash": HASHES[1],
        "source_hash": HASHES[0],
        "base_repository_hash": None,
        "split_id": split.split_id,
        "split": "training",
        "agent_version_id": "fixture-agent-v0",
        "agent_version_hash": HASHES[5],
        "model_identity_hash": HASHES[6],
        "codex_identity_hash": HASHES[7],
        "auth_semantic_id": "offline.none",
        "prompt_hash": HASHES[8],
        "memory_pack_hash": None,
        "runtime_identity_hash": HASHES[9],
        "image_identity_hash": None,
        "verifier_identity_hash": HASHES[10],
        "toolchain_identity_hash": HASHES[11],
        "base_seed": 0,
        "sample_index": 0,
        "events": [event.model_dump(mode="json")],
        "event_count": 1,
        "events_hash": content_hash([event]),
        "run_manifest_hash": HASHES[12],
        "scorecard_hash": HASHES[13],
        "artifact_manifest_hash": HASHES[14],
        "export_policy_id": "observable_repo_trajectory_v1",
        "eligibility": TrajectoryEligibility(eligible=True, reason="eligible").model_dump(
            mode="json"
        ),
        "reward": reward.model_dump(mode="json"),
        "reward_hash": content_hash(reward),
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solution_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
        "total_bytes": 128,
    }
    return EpisodeTrajectory.model_validate({**base, "trajectory_hash": content_hash(base)})


def _reward_record(trajectory: EpisodeTrajectory) -> RewardDerivationRecord:
    return RewardDerivationRecord(
        run_id=trajectory.run_id,
        source_artifact_hashes={"run_manifest": trajectory.run_manifest_hash},
        reward=trajectory.reward,
        reward_hash=trajectory.reward_hash,
        scalar_profile_id=REPO_RTL_SPARSE_V1.profile_id,
        scalar_profile_hash=REPO_RTL_SPARSE_V1.profile_hash,
        scalar_reward=1.0,
    )


def _dataset_manifest(
    split: TaskSplitManifest, trajectory: EpisodeTrajectory
) -> TrajectoryDatasetManifest:
    return TrajectoryDatasetManifest(
        dataset_id="training-reference-fixture",
        source_experiment_ids=["training-reference-experiment"],
        input_set_hash=HASHES[0],
        split_manifest_hash=split.manifest_hash,
        agent_version_manifest_hash=HASHES[1],
        export_policy_hash=HASHES[2],
        reward_profile_hash=REPO_RTL_SPARSE_V1.profile_hash,
        included_run_ids=[trajectory.run_id],
        excluded_runs={},
        record_count=1,
        eligible_record_count=1,
        byte_count=128,
        licenses=["Apache-2.0"],
        attributions=["fixture"],
        source_commit="a" * 40,
        package_identities={"verigym": HASHES[3]},
        dataset_hash=HASHES[4],
    )


def _model_root(root: Path) -> Path:
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Qwen3_5ForConditionalGeneration"],
                "model_type": "qwen3_5",
                "transformers_version": "4.57.0.dev0",
            }
        ),
        encoding="utf-8",
    )
    (root / "tokenizer_config.json").write_text("{}\n", encoding="utf-8")
    (root / "model-00001-of-00001.safetensors").write_bytes(b"weights")
    (root / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                "metadata": {"total_size": 7},
                "weight_map": {"model.weight": "model-00001-of-00001.safetensors"},
            }
        ),
        encoding="utf-8",
    )
    return root


def _config() -> TrainingReferenceConfig:
    return TrainingReferenceConfig(
        framework="trl",
        algorithm="grpo",
        model_id="Qwen/Qwen3.5-9B",
        adapter_type="lora",
        hyperparameters={"learning_rate": 1e-6, "num_generations": 4},
    )


def _patch_dataset_loaders(
    monkeypatch: pytest.MonkeyPatch,
    dataset: Path,
    split: TaskSplitManifest,
    trajectory: EpisodeTrajectory,
    dataset_manifest: TrajectoryDatasetManifest,
) -> None:
    original_json_model = pipeline.load_json_model
    original_jsonl_models = pipeline.load_jsonl_models

    def fake_json_model(path: Path, model: type[Any]) -> Any:
        if path.parent == dataset:
            if model is TaskSplitManifest:
                return split
            if model.__name__ == "RewardProfile":
                return REPO_RTL_SPARSE_V1
        return original_json_model(path, model)

    def fake_jsonl_models(path: Path, model: type[Any]) -> list[Any]:
        if path.parent == dataset:
            if model is EpisodeTrajectory:
                return [trajectory]
            if model is RewardDerivationRecord:
                return [_reward_record(trajectory)]
        return original_jsonl_models(path, model)

    monkeypatch.setattr(pipeline, "validate_trajectory_dataset", lambda _: dataset_manifest)
    monkeypatch.setattr(pipeline, "load_json_model", fake_json_model)
    monkeypatch.setattr(pipeline, "load_jsonl_models", fake_jsonl_models)


def test_prepare_validate_and_register_reference_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "source-dataset"
    dataset.mkdir()
    split = _split()
    trajectory = _trajectory(split)
    dataset_manifest = _dataset_manifest(split, trajectory)
    _patch_dataset_loaders(monkeypatch, dataset, split, trajectory, dataset_manifest)
    model_root = _model_root(tmp_path / "model")
    bundle = tmp_path / "bundle"

    prepared = prepare_training_bundle(
        dataset,
        bundle,
        config=_config(),
        model_root=model_root,
    )

    assert prepared.record_count == 1
    assert prepared.training_task_ids == ["fixture/train"]
    assert prepared.model_snapshot.actual_weight_bytes == 7
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(bundle.iterdir()) if path.is_file()
    )
    assert str(tmp_path) not in serialized
    assert validate_training_bundle(bundle, source_dataset=dataset) == prepared

    oracle = TrainingRewardOracle(
        bundle=bundle,
        source_dataset=dataset,
        output_root=tmp_path / "reward-runs",
    )
    with pytest.raises(ConfigurationError, match="training split"):
        oracle.score("fixture/heldout", "module demo; endmodule\n")
    with pytest.raises(ConfigurationError, match="training split"):
        oracle.task_prompt("fixture/heldout")

    class FakeOracle:
        manifest = prepared

        @staticmethod
        def task_prompt(task_id: str) -> list[dict[str, str]]:
            return [{"role": "user", "content": task_id}]

        @staticmethod
        def score(task_id: str, candidate: str) -> Any:
            assert task_id == "fixture/train"
            assert candidate == "module demo; endmodule"
            return SimpleNamespace(scalar_reward=1.0, infrastructure_valid=True)

    fake_oracle = FakeOracle()
    assert build_trl_dataset_rows(fake_oracle) == [
        {
            "prompt": [{"role": "user", "content": "fixture/train"}],
            "task_id": "fixture/train",
        }
    ]
    assert TrlRewardAdapter(fake_oracle)(
        completions=[[{"role": "assistant", "content": "module demo; endmodule"}]],
        task_id=["fixture/train"],
    ) == [1.0]

    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "adapter_model.safetensors").write_bytes(b"adapter")
    imported = register_checkpoint(
        bundle,
        checkpoint,
        tmp_path / "checkpoint-import.json",
        source_dataset=dataset,
        import_id="qwen35-rtl-lora-v1",
        parent_version_hash=HASHES[5],
        compatible_runtime_hash=HASHES[6],
        license="Apache-2.0",
        provenance="external-reference-smoke",
        loading_configuration={"format": "safetensors", "revision": "step-1"},
    )
    assert imported.update_type == "external_adapter"
    assert imported.trainer_identity_hash == prepared.trainer_identity_hash
    assert imported.executable_in_m10b is False


def test_bundle_validation_rejects_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "source-dataset"
    dataset.mkdir()
    split = _split()
    trajectory = _trajectory(split)
    dataset_manifest = _dataset_manifest(split, trajectory)
    _patch_dataset_loaders(monkeypatch, dataset, split, trajectory, dataset_manifest)
    bundle = tmp_path / "bundle"
    prepare_training_bundle(
        dataset,
        bundle,
        config=_config(),
        model_root=_model_root(tmp_path / "model"),
    )
    with (bundle / "episodes.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("\n")

    with pytest.raises(ConfigurationError):
        validate_training_bundle(bundle, source_dataset=dataset)


def test_model_snapshot_and_config_fail_closed(tmp_path: Path) -> None:
    snapshot = inspect_model_snapshot(
        _model_root(tmp_path / "model"),
        model_id="Qwen/Qwen3.5-9B",
    )
    assert snapshot.model_type == "qwen3_5"
    assert snapshot.weights_content_hashed is False
    assert snapshot.raw_host_path_exported is False

    with pytest.raises(ValidationError, match="credential-like"):
        TrainingReferenceConfig(
            framework="trl",
            algorithm="grpo",
            model_id="Qwen/Qwen3.5-9B",
            hyperparameters={"api_key": "forbidden"},
        )


def test_bundle_files_remain_strict_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "source-dataset"
    dataset.mkdir()
    split = _split()
    trajectory = _trajectory(split)
    dataset_manifest = _dataset_manifest(split, trajectory)
    _patch_dataset_loaders(monkeypatch, dataset, split, trajectory, dataset_manifest)
    bundle = tmp_path / "bundle"
    manifest = prepare_training_bundle(
        dataset,
        bundle,
        config=_config(),
        model_root=_model_root(tmp_path / "model"),
    )

    assert load_json_model(bundle / "bundle-manifest.json", type(manifest)) == manifest
    assert load_jsonl_models(bundle / "episodes.jsonl", EpisodeTrajectory) == [trajectory]

    (bundle / "unexpected.txt").write_text("not sealed\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unexpected"):
        validate_training_bundle(bundle, source_dataset=dataset)
