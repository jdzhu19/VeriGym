from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.splits import build_task_split
from verigym.evolution.training_transcript import build_teacher_transcript
from verigym.experiments.state import atomic_dump_json
from verigym.protocols.repository_action import (
    canonical_tool_observation,
    repository_tool_definitions,
)
from verigym.schemas.evolution import TaskSplitEntry
from verigym.schemas.multiturn_sft import (
    MultiTurnSftMessage,
    VerifiedMultiTurnSftDatasetManifest,
    seal_multi_turn_example,
)

from verigym_training_reference.multiturn_sft_exporter import (
    TranscriptRunBinding,
    bindings_from_cva6_collection,
    export_verified_multiturn_sft,
)
from verigym_training_reference.multiturn_sft_training import (
    EXPECTED_STEPS,
    MAX_LENGTH,
    assert_resolved_verl_config,
    load_frozen_multiturn_dataset,
    sft_spec_kwargs,
)
from verigym_training_reference.verl_lora_dropout import wrap_lora_config


def _example(index: int) -> dict[str, object]:
    call_id = f"call_{index}"
    messages = [
        {"role": "system", "content": "Use repository tools."},
        {"role": "user", "content": f"Repair task {index}."},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "finish", "arguments": '{"message":"done"}'},
                }
            ],
        },
        {
            "role": "tool",
            "name": "finish",
            "tool_call_id": call_id,
            "content": canonical_tool_observation(
                "finish", {"accepted": True, "terminal": True}, is_error=False
            ),
        },
        {"role": "assistant", "content": "Done."},
    ]
    hash_character = format(index, "x")
    return seal_multi_turn_example(
        {
            "sample_id": hash_character * 64,
            "task_id": f"hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-{2000 + index}",
            "official_task_id": f"openhwgroup/cva6:pr-{2000 + index}",
            "task_hash": "a" * 64,
            "source_hash": hash_character * 64,
            "candidate_hash": "b" * 64,
            "verifier_hash": "c" * 64,
            "verigym_source_commit": "9" * 64,
            "verigym_source_tree_hash": "8" * 64,
            "provider": "anthropic-compatible",
            "model_id": "deepseek-v4-flash[1m]",
            "reasoning_effort": "max",
            "client_kind": "cli",
            "client_name": "claude-code",
            "client_version": "1",
            "prompt_hash": "d" * 64,
            "tool_contract_hash": content_hash(repository_tool_definitions(dialect="openai")),
            "harness_hash": "e" * 64,
            "tokenizer_hash": "f" * 64,
            "messages": messages,
            "token_count": 64,
        }
    ).model_dump(mode="json")


def _dataset(root: Path) -> None:
    examples = [_example(index) for index in range(1, 9)]
    examples.sort(key=lambda value: value["task_id"])
    payload = "".join(json.dumps(value, sort_keys=True) + "\n" for value in examples).encode()
    (root / "train.jsonl").write_bytes(payload)
    base = {
        "record_count": 8,
        "task_ids": [value["task_id"] for value in examples],
        "example_hashes": [value["example_hash"] for value in examples],
        "tokenizer_hash": "f" * 64,
        "tool_contract_hash": content_hash(repository_tool_definitions(dialect="openai")),
        "verigym_source_commits": ["9" * 64],
        "verigym_source_tree_hashes": ["8" * 64],
        "records_sha256": hash_bytes(payload),
    }
    draft = VerifiedMultiTurnSftDatasetManifest.model_construct(**base, manifest_hash="0" * 64)
    normalized = draft.model_dump(mode="json", exclude={"manifest_hash"})
    manifest = VerifiedMultiTurnSftDatasetManifest.model_validate(
        {**base, "manifest_hash": content_hash(normalized)}
    )
    atomic_dump_json(root / "dataset-manifest.json", manifest)


def test_frozen_training_input_requires_exact_eight_and_current_tool_contract(
    tmp_path: Path,
) -> None:
    _dataset(tmp_path)

    inputs = load_frozen_multiturn_dataset(tmp_path)

    assert len(inputs.rows) == 8
    assert all(set(row) == {"messages"} for row in inputs.rows)
    train = tmp_path / "train.jsonl"
    train.write_bytes(train.read_bytes() + b"\n")
    with pytest.raises(ConfigurationError, match="manifest"):
        load_frozen_multiturn_dataset(tmp_path)


def test_frozen_sft_spec_is_exact_and_resolved_config_is_checked(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    model = tmp_path / "model"
    output = tmp_path / "output"
    dataset.mkdir()
    model.mkdir()
    _dataset(dataset)
    inputs = load_frozen_multiturn_dataset(dataset)

    kwargs = sft_spec_kwargs(inputs, model_root=model, output=output)

    assert kwargs["epochs"] == 3
    assert kwargs["batch_size"] == 4
    assert kwargs["max_length"] == MAX_LENGTH
    assert kwargs["tokenize_method"] == "hf_template"
    assert kwargs["lora_rank"] == 8
    overrides = kwargs["overrides"]
    assert overrides["model"]["lora"]["dropout"] == 0.05
    assert overrides["engine"] == {
        "strategy": "fsdp2",
        "model_dtype": "bf16",
        "dtype": "bfloat16",
        "seed": 484,
    }
    assert overrides["trainer"]["total_training_steps"] == EXPECTED_STEPS

    config = SimpleNamespace(
        model=SimpleNamespace(
            lora_rank=8,
            lora_alpha=16,
            lora=SimpleNamespace(dropout=0.05),
            external_lib="verigym_training_reference.verl_lora_dropout",
            enable_gradient_checkpointing=True,
        ),
        engine=SimpleNamespace(strategy="fsdp2", model_dtype="bf16", dtype="bfloat16", seed=484),
        data=SimpleNamespace(
            train_batch_size=4,
            micro_batch_size_per_gpu=1,
            max_length=MAX_LENGTH,
            truncation="error",
            use_dynamic_bsz=False,
            rllm=SimpleNamespace(tokenize_and_mask_method="hf_template"),
        ),
        optim=SimpleNamespace(lr=1e-4),
        trainer=SimpleNamespace(
            total_epochs=3,
            total_training_steps=EXPECTED_STEPS,
            seed=484,
            nnodes=1,
            n_gpus_per_node=4,
            default_local_dir=str(output),
        ),
    )
    assert_resolved_verl_config(config, output=output)
    config.data.truncation = "right"
    with pytest.raises(ConfigurationError, match="data.truncation"):
        assert_resolved_verl_config(config, output=output)


def test_verl_lora_compat_injects_frozen_dropout_and_rejects_conflicts() -> None:
    observed: list[dict[str, object]] = []

    def factory(**kwargs: object) -> dict[str, object]:
        observed.append(kwargs)
        return kwargs

    wrapped = wrap_lora_config(factory)
    assert wrapped(r=8)["lora_dropout"] == 0.05
    assert observed == [{"r": 8, "lora_dropout": 0.05}]
    assert wrap_lora_config(wrapped) is wrapped
    with pytest.raises(RuntimeError, match="requires lora_dropout"):
        wrapped(r=8, lora_dropout=0.1)


def test_collection_receipt_resolves_only_bound_relative_paths(tmp_path: Path) -> None:
    entries = [
        TaskSplitEntry(
            task_id=f"suite/task-{index}",
            source_hash=format(index, "x") * 64,
            task_hash=format((index + 8) % 16, "x") * 64,
            license="Apache-2.0",
            attribution="training",
        )
        for index in range(1, 9)
    ]
    split = build_task_split(split_id="collection-split", training=entries, heldout=[])
    split_path = tmp_path / "task-split.json"
    atomic_dump_json(split_path, split)
    collection = tmp_path / "collection"
    collection.mkdir()
    rows: list[dict[str, object]] = []
    for index, entry in enumerate(entries):
        run = collection / "runs" / f"attempt-{index}"
        run.mkdir(parents=True)
        transcript = run / "training-transcript.json"
        transcript.write_text("{}\n", encoding="utf-8")
        rows.append(
            {
                "task_id": entry.task_id,
                "provider": "claude",
                "attempt_id": f"attempt-{index}",
                "run": run.relative_to(collection).as_posix(),
                "transcript": transcript.relative_to(collection).as_posix(),
                "token_count": 1,
                "transcript_hash": format(index + 1, "x") * 64,
            }
        )
    progress = {
        "format_id": "verigym_cva6_teacher_collection_v1",
        "status": "completed",
        "task_split_hash": split.manifest_hash,
        "successes": rows,
    }
    atomic_dump_json(collection / "collection-progress.json", progress)
    receipt = {
        "format_id": "verigym_cva6_teacher_bindings_v1",
        "task_split_hash": split.manifest_hash,
        "record_count": 8,
        "bindings": rows,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
    }
    atomic_dump_json(collection / "successful-bindings.json", receipt)

    bindings = bindings_from_cva6_collection(collection, split_manifest_path=split_path)
    assert len(bindings) == 8
    assert all(binding.transcript.is_relative_to(collection) for binding in bindings)

    rows[0]["transcript"] = "../escaped.json"
    receipt["bindings"] = rows
    progress["successes"] = rows
    atomic_dump_json(collection / "collection-progress.json", progress)
    atomic_dump_json(collection / "successful-bindings.json", receipt)
    with pytest.raises(ConfigurationError, match="does not exist|escapes"):
        bindings_from_cva6_collection(collection, split_manifest_path=split_path)


class _Tokenizer:
    def apply_chat_template(
        self,
        conversation: list[dict[str, object]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> str:
        del tokenize, add_generation_prompt
        return "".join(
            f"<{message['role']}>{message.get('content') or ''}" for message in conversation
        )

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        del add_special_tokens
        return list(text.encode())


def test_multiturn_export_rejects_heldout_before_reading_run(tmp_path: Path) -> None:
    training = TaskSplitEntry(
        task_id="suite/training",
        source_hash="1" * 64,
        task_hash="2" * 64,
        license="Apache-2.0",
        attribution="training",
    )
    heldout = TaskSplitEntry(
        task_id="suite/heldout",
        source_hash="3" * 64,
        task_hash="4" * 64,
        license="Apache-2.0",
        attribution="heldout",
    )
    split = build_task_split(split_id="split-v1", training=[training], heldout=[heldout])
    split_path = tmp_path / "task-split.json"
    atomic_dump_json(split_path, split)
    messages = [
        MultiTurnSftMessage(role="system", content="system"),
        MultiTurnSftMessage(role="user", content="user"),
        MultiTurnSftMessage.model_validate(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "finish",
                            "arguments": '{"message":"done"}',
                        },
                    }
                ],
            }
        ),
        MultiTurnSftMessage(
            role="tool",
            name="finish",
            tool_call_id="call_1",
            content=canonical_tool_observation(
                "finish", {"accepted": True, "terminal": True}, is_error=False
            ),
        ),
        MultiTurnSftMessage(role="assistant", content="done"),
    ]
    transcript = build_teacher_transcript(
        campaign_role="training",
        task_id="suite/heldout",
        provider="provider",
        model_id="model",
        reasoning_effort="max",
        client_kind="cli",
        client_name="client",
        client_version="1",
        harness_identity={"kind": "test"},
        messages=messages,
    )
    transcript_path = tmp_path / "training-transcript.json"
    atomic_dump_json(transcript_path, transcript)
    tokenizer_root = tmp_path / "tokenizer"
    tokenizer_root.mkdir()
    (tokenizer_root / "tokenizer_config.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="not in the frozen training split"):
        export_verified_multiturn_sft(
            [TranscriptRunBinding(transcript=transcript_path, run=tmp_path / "missing-run")],
            split_manifest_path=split_path,
            tokenizer=_Tokenizer(),
            tokenizer_root=tokenizer_root,
            output=tmp_path / "output",
        )
