"""Frozen eight-example Qwen3.5 multi-turn SFT mainline."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.protocols.repository_action import repository_tool_definitions
from verigym.schemas.multiturn_sft import (
    VerifiedMultiTurnSftDatasetManifest,
    VerifiedMultiTurnSftExample,
)

RLLM_COMMIT = "1d1109a655e291b3001d8526d7c9ecc5b9328226"
VERL_VERSION = "0.8.0"
VLLM_VERSION = "0.22.1"
EXPECTED_RECORDS = 8
EXPECTED_STEPS = 6
MAX_LENGTH = 16_384
SEED = 484
OPT_IN_ENV = "VERIGYM_RUN_QWEN35_MULTITURN_SFT"
_MAX_DATASET_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class FrozenSftInputs:
    """Validated input identities and rLLM-compatible message rows."""

    dataset_root: Path
    manifest: VerifiedMultiTurnSftDatasetManifest
    rows: list[dict[str, Any]]
    train_jsonl_sha256: str


def load_frozen_multiturn_dataset(path: Path) -> FrozenSftInputs:
    """Load exactly eight sealed examples without following input symlinks."""

    root = _safe_directory(path, "dataset")
    manifest_path = root / "dataset-manifest.json"
    train_path = root / "train.jsonl"
    manifest = VerifiedMultiTurnSftDatasetManifest.model_validate(
        json.loads(_read_regular_file(manifest_path))
    )
    if manifest.record_count != EXPECTED_RECORDS:
        raise ConfigurationError(
            f"multi-turn SFT requires exactly {EXPECTED_RECORDS} records; "
            f"found {manifest.record_count}"
        )
    train_payload = _read_regular_file(train_path)
    train_hash = hash_bytes(train_payload)
    if train_hash != manifest.records_sha256:
        raise ConfigurationError("train.jsonl differs from the sealed dataset manifest")
    raw_lines = train_payload.decode("utf-8").splitlines()
    if len(raw_lines) != EXPECTED_RECORDS or any(not line for line in raw_lines):
        raise ConfigurationError("train.jsonl must contain exactly eight non-empty records")

    examples = [VerifiedMultiTurnSftExample.model_validate_json(line) for line in raw_lines]
    if [example.task_id for example in examples] != manifest.task_ids:
        raise ConfigurationError("dataset task ordering differs from its manifest")
    if [example.example_hash for example in examples] != manifest.example_hashes:
        raise ConfigurationError("dataset example identities differ from their manifest")
    if any(example.tokenizer_hash != manifest.tokenizer_hash for example in examples):
        raise ConfigurationError("dataset contains mixed tokenizer identities")
    if any(example.tool_contract_hash != manifest.tool_contract_hash for example in examples):
        raise ConfigurationError("dataset contains mixed tool-contract identities")
    current_tool_hash = content_hash(repository_tool_definitions(dialect="openai"))
    if manifest.tool_contract_hash != current_tool_hash:
        raise ConfigurationError("dataset uses a stale repository tool contract")
    rows = [{"messages": example.model_dump(mode="json")["messages"]} for example in examples]
    return FrozenSftInputs(root, manifest, rows, train_hash)


def sft_spec_kwargs(
    inputs: FrozenSftInputs,
    *,
    model_root: Path,
    output: Path,
) -> dict[str, Any]:
    """Return the exact backend-neutral and veRL overrides for the frozen run."""

    model = _safe_directory(model_root, "model")
    destination = _new_output_directory(output)
    return {
        "model": str(model),
        "lr": 1e-4,
        "lr_schedule": "constant",
        "epochs": 3,
        "batch_size": 4,
        "max_length": MAX_LENGTH,
        "tokenize_method": "hf_template",
        "lora_rank": 8,
        "save_freq": EXPECTED_STEPS,
        "val_freq": -1,
        "project": "verigym-verified-multiturn-sft",
        "experiment": f"qwen35-9b-seed-{SEED}",
        "output_dir": str(destination),
        "overrides": {
            "model": {
                "lora_rank": 8,
                "lora_alpha": 16,
                "lora": {"dropout": 0.05},
                "external_lib": "verigym_training_reference.verl_lora_dropout",
                "enable_gradient_checkpointing": True,
            },
            "engine": {
                "strategy": "fsdp2",
                "model_dtype": "bf16",
                "dtype": "bfloat16",
                "seed": SEED,
            },
            "data": {
                "train_batch_size": 4,
                "micro_batch_size_per_gpu": 1,
                "max_length": MAX_LENGTH,
                "truncation": "error",
                "use_dynamic_bsz": False,
            },
            "trainer": {
                "total_epochs": 3,
                "total_training_steps": EXPECTED_STEPS,
                "save_freq": EXPECTED_STEPS,
                "test_freq": -1,
                "seed": SEED,
                "nnodes": 1,
                "n_gpus_per_node": 4,
                "logger": ["console"],
            },
        },
        "_rows": inputs.rows,
    }


def validate_runtime_pins(rllm_source: Path) -> dict[str, str]:
    """Require the frozen trainer and separately bound model-service versions."""

    source = _safe_directory(rllm_source, "rLLM source")
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigurationError("cannot identify the frozen rLLM checkout") from exc
    commit = result.stdout.strip()
    if commit != RLLM_COMMIT:
        raise ConfigurationError(f"rLLM commit must be {RLLM_COMMIT}; found {commit}")
    try:
        importlib.metadata.version("vllm")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise ConfigurationError("the SFT interpreter must not embed the vLLM service package")
    versions = {
        "rllm_commit": commit,
        "verl": _package_version("verl"),
        "vllm": os.environ.get("VERIGYM_VLLM_SERVICE_VERSION", ""),
    }
    if versions["verl"] != VERL_VERSION or versions["vllm"] != VLLM_VERSION:
        raise ConfigurationError(
            f"training requires verl=={VERL_VERSION} and vllm=={VLLM_VERSION}; "
            f"found verl=={versions['verl']} and vllm=={versions['vllm']}"
        )
    return versions


def assert_resolved_verl_config(config: Any, *, output: Path) -> None:
    """Verify the effective config rather than trusting requested overrides."""

    expected = {
        "model.lora_rank": 8,
        "model.lora_alpha": 16,
        "model.lora.dropout": 0.05,
        "model.external_lib": "verigym_training_reference.verl_lora_dropout",
        "model.enable_gradient_checkpointing": True,
        "engine.strategy": "fsdp2",
        "engine.model_dtype": "bf16",
        "engine.dtype": "bfloat16",
        "engine.seed": SEED,
        "data.train_batch_size": 4,
        "data.micro_batch_size_per_gpu": 1,
        "data.max_length": MAX_LENGTH,
        "data.truncation": "error",
        "data.use_dynamic_bsz": False,
        "data.rllm.tokenize_and_mask_method": "hf_template",
        "optim.lr": 1e-4,
        "trainer.total_epochs": 3,
        "trainer.total_training_steps": EXPECTED_STEPS,
        "trainer.seed": SEED,
        "trainer.nnodes": 1,
        "trainer.n_gpus_per_node": 4,
    }
    for dotted, value in expected.items():
        observed = _nested_value(config, dotted)
        if observed != value:
            raise ConfigurationError(
                f"resolved veRL setting {dotted} must be {value!r}; found {observed!r}"
            )
    if Path(str(_nested_value(config, "trainer.default_local_dir"))).resolve() != output.resolve():
        raise ConfigurationError("veRL checkpoint directory differs from the requested output")


def run_frozen_multiturn_sft(
    *,
    dataset: Path,
    model_root: Path,
    output: Path,
    rllm_source: Path,
) -> dict[str, Any]:
    """Run the fixed six-step AgentSFTTrainer job and seal its report."""

    if os.environ.get(OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPT_IN_ENV}=1 is required")
    inputs = load_frozen_multiturn_dataset(dataset)
    versions = validate_runtime_pins(rllm_source)
    kwargs = sft_spec_kwargs(inputs, model_root=model_root, output=output)
    rows = kwargs.pop("_rows")

    from rllm.data import Dataset  # type: ignore[import-not-found]
    from rllm.trainer.agent_sft_trainer import (  # type: ignore[import-not-found]
        AgentSFTTrainer,
    )
    from rllm.trainer.sft import SFTSpec  # type: ignore[import-not-found]

    spec = SFTSpec(
        train_dataset=Dataset(data=rows, name="verigym-cva6-multiturn", split="train"),
        **kwargs,
    )
    trainer = AgentSFTTrainer(spec, backend="verl")
    backend = trainer.prepare()
    destination = Path(spec.output_dir or "")
    assert_resolved_verl_config(backend.config, output=destination)
    resolved_config_path = Path(backend.serialize_config())
    resolved_config_hash = hash_bytes(resolved_config_path.read_bytes())
    trainer.train()

    checkpoint = destination / f"global_step_{EXPECTED_STEPS}"
    adapter = _export_adapter_checkpoint(checkpoint, destination=destination)
    _validate_adapter_checkpoint(adapter)
    artifact_hash, inventory = _artifact_inventory(destination)
    report = {
        "format_id": "verigym_qwen35_multiturn_sft_report_v1",
        "status": "completed",
        "optimizer_steps": EXPECTED_STEPS,
        "epochs": 3,
        "global_batch_size": 4,
        "micro_batch_size_per_gpu": 1,
        "gradient_accumulation_steps": 1,
        "world_size": 4,
        "precision": "bf16",
        "strategy": "fsdp2",
        "gradient_checkpointing": True,
        "lora": {"rank": 8, "alpha": 16, "dropout": 0.05},
        "learning_rate": 1e-4,
        "seed": SEED,
        "max_length": MAX_LENGTH,
        "truncation": "error",
        "tokenize_method": "hf_template",
        "dataset_manifest_hash": inputs.manifest.manifest_hash,
        "dataset_records_sha256": inputs.train_jsonl_sha256,
        "tokenizer_hash": inputs.manifest.tokenizer_hash,
        "tool_contract_hash": inputs.manifest.tool_contract_hash,
        "rllm_commit": versions["rllm_commit"],
        "verl_version": versions["verl"],
        "vllm_version": versions["vllm"],
        "resolved_config_sha256": resolved_config_hash,
        "checkpoint": checkpoint.relative_to(destination).as_posix(),
        "adapter": adapter.relative_to(destination).as_posix(),
        "artifact_hash": artifact_hash,
        "artifacts": inventory,
        "reload_smoke": "pending",
    }
    report["report_hash"] = content_hash(report)
    _atomic_json(destination / "training-report.json", report)
    return report


def _validate_adapter_checkpoint(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        raise ConfigurationError(f"expected final checkpoint is missing: {path.name}")
    config_path = path / "adapter_config.json"
    if not config_path.is_file() or config_path.is_symlink():
        raise ConfigurationError("final checkpoint is not a PEFT adapter")
    config = json.loads(_read_regular_file(config_path))
    if (
        config.get("r") != 8
        or config.get("lora_alpha") != 16
        or float(config.get("lora_dropout", -1)) != 0.05
    ):
        raise ConfigurationError("saved adapter LoRA settings differ from the frozen run")
    if not any(path.glob("adapter_model*.safetensors")):
        raise ConfigurationError("final adapter has no safetensors weights")


def _export_adapter_checkpoint(checkpoint: Path, *, destination: Path) -> Path:
    """Convert the fixed veRL FSDP checkpoint to a compact PEFT adapter."""

    if not checkpoint.is_dir() or checkpoint.is_symlink():
        raise ConfigurationError(f"expected final checkpoint is missing: {checkpoint.name}")
    adapter = destination / "lora_adapter"
    if adapter.exists():
        raise ConfigurationError("LoRA adapter output already exists")

    try:
        from verl.model_merger.base_model_merger import (  # type: ignore[import-not-found]
            ModelMergerConfig,
        )
        from verl.model_merger.fsdp_model_merger import (  # type: ignore[import-not-found]
            FSDPModelMerger,
        )

        config = ModelMergerConfig(
            operation="merge",
            backend="fsdp",
            local_dir=str(checkpoint),
            target_dir=str(destination),
            hf_model_config_path=str(checkpoint / "huggingface"),
        )
        merger = FSDPModelMerger(config)
        world_size = merger._get_world_size()
        rank_zero = merger._load_rank_zero_state_dict(world_size)
        mesh, mesh_names = merger._extract_device_mesh_info(rank_zero, world_size)
        total_shards, mesh_shape = merger._calculate_shard_configuration(mesh, mesh_names)
        state_dict = merger._load_and_merge_state_dicts(
            world_size, total_shards, mesh_shape, mesh_names
        )
        exported = merger.save_lora_adapter(state_dict)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        raise ConfigurationError("failed to export the step-6 veRL LoRA adapter") from exc
    if exported is None or Path(exported).resolve() != adapter.resolve():
        raise ConfigurationError("veRL checkpoint did not contain a LoRA adapter")

    config_path = adapter / "adapter_config.json"
    try:
        adapter_config = json.loads(_read_regular_file(config_path))
    except (OSError, ValueError, TypeError) as exc:
        raise ConfigurationError("veRL produced an invalid adapter configuration") from exc
    if not isinstance(adapter_config, dict):
        raise ConfigurationError("veRL produced a non-object adapter configuration")
    adapter_config["lora_dropout"] = 0.05
    _atomic_json(config_path, adapter_config)
    return adapter


def _artifact_inventory(root: Path) -> tuple[str, list[dict[str, str | int]]]:
    inventory: list[dict[str, str | int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ConfigurationError("training output contains a symlink")
        if not path.is_file() or path.name == "training-report.json":
            continue
        inventory.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    identity = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(identity).hexdigest(), inventory


def _nested_value(config: Any, dotted: str) -> Any:
    value = config
    for component in dotted.split("."):
        if isinstance(value, dict):
            value = value[component]
        else:
            value = getattr(value, component)
    return value


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ConfigurationError(f"required training package is not installed: {name}") from exc


def _safe_directory(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ConfigurationError(f"{label} cannot be a symlink")
    try:
        resolved = expanded.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"{label} does not exist") from exc
    if not resolved.is_dir():
        raise ConfigurationError(f"{label} must be a directory")
    return resolved


def _new_output_directory(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.exists():
        if expanded.is_symlink() or not expanded.is_dir() or any(expanded.iterdir()):
            raise ConfigurationError("training output must be a new or empty real directory")
    else:
        expanded.mkdir(parents=True)
    return expanded.resolve(strict=True)


def _read_regular_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(f"expected a regular input file: {path.name}")
    before = path.stat()
    if before.st_size <= 0 or before.st_size > _MAX_DATASET_BYTES:
        raise ConfigurationError(f"input is empty or oversized: {path.name}")
    payload = path.read_bytes()
    after = path.stat()
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before.st_size != len(payload) or before_identity != after_identity:
        raise ConfigurationError(f"input changed while reading: {path.name}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


__all__ = [
    "EXPECTED_RECORDS",
    "EXPECTED_STEPS",
    "FrozenSftInputs",
    "MAX_LENGTH",
    "OPT_IN_ENV",
    "RLLM_COMMIT",
    "SEED",
    "VERL_VERSION",
    "VLLM_VERSION",
    "assert_resolved_verl_config",
    "load_frozen_multiturn_dataset",
    "run_frozen_multiturn_sft",
    "sft_spec_kwargs",
    "validate_runtime_pins",
]
