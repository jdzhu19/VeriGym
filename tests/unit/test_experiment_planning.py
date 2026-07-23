from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.milestone9_helpers import experiment_config, offline_service
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.experiments.config import load_experiment_config
from verigym.experiments.identity import (
    derive_child_seed,
    normalized_runtime_descriptor,
    plan_item_identity_payload,
    runtime_identity_hash,
)
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig
from verigym.schemas.common import RuntimeImageIdentity, RuntimeResourceSummary


def test_experiment_schema_round_trip_is_strict_and_secret_free(tmp_path: Path) -> None:
    config = experiment_config(tmp_path / "out")
    assert ExperimentConfig.model_validate_json(config.model_dump_json()) == config
    assert config.identity_payload()["output"] == {"root": "."}
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ExperimentConfig.model_validate(
            {**config.model_dump(mode="json"), "api_key": "must-not-be-accepted"}
        )
    with pytest.raises(ValidationError, match="model sample_index"):
        experiment_config(
            tmp_path / "sample-owned",
            mode="chat",
            systems=[
                {
                    "id": "chat",
                    "agent": {"id": "single-turn"},
                    "model": {
                        "id": "static-and-gate-mixed",
                        "options": {"sample_index": 0},
                    },
                }
            ],
        )


@pytest.mark.parametrize(
    "runs",
    [
        {"seeds": [], "samples_per_task": 1, "pass_k": [1]},
        {"seeds": [1, 1], "samples_per_task": 1, "pass_k": [1]},
        {"seeds": [-1], "samples_per_task": 1, "pass_k": [1]},
        {"seeds": [0], "samples_per_task": 0, "pass_k": [1]},
        {"seeds": [0], "samples_per_task": 2, "pass_k": [0]},
        {"seeds": [0], "samples_per_task": 2, "pass_k": [3]},
        {"seeds": [0], "samples_per_task": 2, "pass_k": [1, 1]},
    ],
)
def test_seed_sample_and_k_validation(tmp_path: Path, runs: dict[str, object]) -> None:
    payload = experiment_config(tmp_path / "valid").model_dump(mode="json")
    payload["runs"] = {"mode": "agent", **runs}
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate(payload)


def test_bounded_loader_rejects_duplicates_alias_cycles_depth_and_symlinks(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema_version: '1.0'\nname: one\nname: two\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="duplicate"):
        load_experiment_config(duplicate)

    cyclic = tmp_path / "cyclic.yaml"
    cyclic.write_text("value: &loop [*loop]\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="recursive YAML aliases"):
        load_experiment_config(cyclic)

    nested: object = "leaf"
    for _index in range(40):
        nested = {"level": nested}
    deep = tmp_path / "deep.json"
    deep.write_text(json.dumps(nested), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="depth"):
        load_experiment_config(deep)

    link = tmp_path / "link.yaml"
    link.symlink_to(duplicate)
    with pytest.raises(ConfigurationError, match="non-symlink"):
        load_experiment_config(link)


def test_planning_is_deterministic_and_host_output_order_independent(tmp_path: Path) -> None:
    systems = [
        {"id": "z-bad", "agent": {"id": "scripted-bad"}},
        {"id": "a-good", "agent": {"id": "scripted"}},
    ]
    first_config = experiment_config(
        tmp_path / "first",
        tasks=["counter-basic", "and-gate-basic"],
        systems=systems,
        seeds=[9, 2],
    )
    second_config = experiment_config(
        tmp_path / "second",
        tasks=["and-gate-basic", "counter-basic"],
        systems=list(reversed(systems)),
        seeds=[2, 9],
        max_workers=4,
    )
    planner = ExperimentPlanner(offline_service())
    first = planner.build(first_config)
    second = planner.build(second_config)
    assert len(first.items) == 8
    assert [
        (item.task_id, item.system.system_id, item.base_seed, item.sample_index)
        for item in first.items
    ] == sorted(
        (item.task_id, item.system.system_id, item.base_seed, item.sample_index)
        for item in first.items
    )
    assert [item.plan_item_id for item in first.items] == [
        item.plan_item_id for item in second.items
    ]
    assert first.plan_hash == second.plan_hash
    assert first.task_set_hash == second.task_set_hash
    assert first.evaluation_config_hash == second.evaluation_config_hash


def test_plan_item_identity_tracks_every_frozen_field_but_not_order() -> None:
    item = (
        ExperimentPlanner(offline_service())
        .build(experiment_config(Path("unused"), tasks=["counter-basic"], seeds=[0]))
        .items[0]
    )
    raw = item.model_dump(mode="json")
    baseline = content_hash(plan_item_identity_payload(raw))
    for field in sorted(set(raw) - {"plan_index", "plan_item_id"}):
        mutated = copy.deepcopy(raw)
        mutated[field] = {"changed_field": field, "old_hash": content_hash(mutated[field])}
        assert content_hash(plan_item_identity_payload(mutated)) != baseline, field
    order_only = copy.deepcopy(raw)
    order_only["plan_index"] = 999
    order_only["plan_item_id"] = "f" * 64
    assert content_hash(plan_item_identity_payload(order_only)) == baseline


def test_child_seed_is_stable_sensitive_and_signed_64_bit() -> None:
    arguments = {
        "evaluation_config_hash": "a" * 64,
        "task_hash": "b" * 64,
        "system_identity_hash": "c" * 64,
        "base_seed": 17,
        "sample_index": 3,
    }
    value = derive_child_seed(**arguments)
    assert value == derive_child_seed(**arguments)
    assert 0 <= value <= 2**63 - 1
    assert value != derive_child_seed(**{**arguments, "sample_index": 4})
    assert value != derive_child_seed(**{**arguments, "base_seed": 18})


def test_runtime_identity_discards_request_and_session_lifecycle_noise() -> None:
    descriptor = (
        offline_service()
        .registries.runtimes.get("docker")
        .descriptor.model_copy(
            update={
                "configuration_fingerprint": "a" * 64,
                "image": RuntimeImageIdentity(
                    requested_reference="example:tag",
                    resolved_image_id="sha256:" + "b" * 64,
                    os="linux",
                    architecture="amd64",
                ),
                "resources": RuntimeResourceSummary(
                    memory_bytes=512 * 1024 * 1024,
                    memory_swap_bytes=512 * 1024 * 1024,
                    swap_enforced=True,
                    cpus=1.0,
                    pids_limit=128,
                    tmpfs_bytes=64 * 1024 * 1024,
                    max_command_time_s=60,
                    max_output_bytes=100,
                ),
            }
        )
    )
    executed = descriptor.model_copy(deep=True)
    assert executed.image is not None and executed.resources is not None
    executed.image.requested_reference = executed.image.resolved_image_id
    executed.resources.max_output_bytes = 200
    executed.configuration_fingerprint = "c" * 64

    assert runtime_identity_hash(descriptor) == runtime_identity_hash(executed)
    normalized = normalized_runtime_descriptor(descriptor)
    assert normalized.configuration_fingerprint is None
    assert normalized.image is not None
    assert normalized.image.requested_reference == normalized.image.resolved_image_id
    assert normalized.resources is not None
    assert normalized.resources.max_output_bytes is None


def test_plan_integrity_tampering_is_rejected_before_output_or_child_execution(
    tmp_path: Path,
) -> None:
    config = experiment_config(
        tmp_path / "tampered",
        tasks=["counter-basic"],
        systems=[{"id": "good", "agent": {"id": "scripted"}}],
        seeds=[0],
    )
    planner = ExperimentPlanner(offline_service())
    plan = planner.build(config)
    changed_item = plan.items[0].model_copy(update={"task_hash": "0" * 64})
    changed_plan = plan.model_copy(update={"items": [changed_item]})
    with pytest.raises(ConfigurationError, match="ordered plan hash"):
        BatchRunner(planner=planner, service_factory=offline_service).run(changed_plan)
    assert not config.output.root.exists()


def test_task_selection_and_agent_model_pairing_fail_before_execution(tmp_path: Path) -> None:
    planner = ExperimentPlanner(offline_service())
    with pytest.raises(ConfigurationError, match="unknown explicit task"):
        planner.build(experiment_config(tmp_path / "unknown", tasks=["does-not-exist"]))
    with pytest.raises(ConfigurationError, match="selected more than once"):
        planner.build(
            experiment_config(
                tmp_path / "overlap",
                tasks=["toy-rtl/*", "counter-basic"],
            )
        )
    with pytest.raises(ConfigurationError, match="selection is empty"):
        planner.build(
            ExperimentConfig.model_validate(
                {
                    **experiment_config(tmp_path / "empty").model_dump(mode="json"),
                    "suite": {
                        "id": "toy-rtl",
                        "tasks": {"include": ["*"], "exclude": ["*"]},
                    },
                }
            )
        )
    with pytest.raises(ConfigurationError, match="must not specify a model"):
        planner.build(
            experiment_config(
                tmp_path / "model-free",
                systems=[
                    {
                        "id": "bad-pair",
                        "agent": {"id": "scripted"},
                        "model": {"id": "static-counter-good"},
                    }
                ],
            )
        )
    with pytest.raises(ConfigurationError, match="requires a model"):
        planner.build(
            experiment_config(
                tmp_path / "missing-model",
                mode="chat",
                tasks=["and-gate-basic"],
                systems=[{"id": "chat", "agent": {"id": "single-turn"}}],
            )
        )
    with pytest.raises(ConfigurationError, match="independent sample 4"):
        planner.build(
            experiment_config(
                tmp_path / "exhausted-fixture",
                mode="chat",
                tasks=["and-gate-basic"],
                samples=5,
                pass_k=[1, 5],
                systems=[
                    {
                        "id": "chat",
                        "agent": {"id": "single-turn"},
                        "model": {"id": "static-and-gate-mixed"},
                    }
                ],
            )
        )
