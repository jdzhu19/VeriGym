"""Qualification-only rLLM/veRL backend for exact 64K HWE decisions."""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, OmegaConf  # type: ignore[import-not-found]
from rllm.data import Dataset  # type: ignore[import-not-found]
from rllm.trainer.sft.backend import SFTConfigError  # type: ignore[import-not-found]
from rllm.trainer.sft.spec import SFTSpec  # type: ignore[import-not-found]
from rllm.trainer.sft.verl_backend import VerlSFTBackend  # type: ignore[import-not-found]

from .hwe_decision_sft_64k import (
    V4_EXPECTED_RECORDS,
    V4_MAX_LENGTH,
    ToolAwareParquetInputs,
    load_tool_aware_v4_dataset,
    write_tool_aware_parquet,
)

RLLM_COMMIT = "1d1109a655e291b3001d8526d7c9ecc5b9328226"
VERL_VERSION = "0.8.0"
VERL_PACKAGE_VERSION = "0.8.0.dev0"
VERL_COMMIT = "7aed6b230776f963fa09509c10d9c3a767d1102c"
TRANSFORMERS_COMMIT = "e8ea728a3eeeb903e77c7d1bd29267c80a1be71f"
CUSTOM_DATASET_PATH = "pkg://verigym_training_reference.verl_sft_dataset"
CUSTOM_DATASET_NAME = "VeriGymHweDecisionSft64kDataset"
COMPATIBILITY_MODULE = "verigym_training_reference.qwen35_verl_fused_compat"


class VeriGymHweDecisionSft64kBackend(VerlSFTBackend):  # type: ignore[misc]
    """Materialize the exact rows and expose no full training method."""

    name = "verigym_hwe_decision_sft_64k_qualification"

    def __init__(self, spec: SFTSpec, *, inputs: ToolAwareParquetInputs, offload: bool) -> None:
        super().__init__(spec)
        self.inputs = inputs
        self.offload = offload

    def validate_spec(self) -> None:
        rows = self.spec.train_dataset.get_data()
        if len(rows) != V4_EXPECTED_RECORDS or tuple(rows) != self.inputs.rows:
            raise SFTConfigError("64K qualification requires all 83 ordered v4 parquet rows")
        if self.spec.val_dataset is not None:
            raise SFTConfigError("64K qualification does not accept a validation dataset")
        if (
            self.spec.max_length != V4_MAX_LENGTH
            or self.spec.batch_size != 1
            or self.spec.lora_rank != 8
            or self.spec.epochs != 1
        ):
            raise SFTConfigError("64K qualification spec differs from its frozen profile")

    def build_config(self) -> DictConfig:
        cfg = super().build_config()
        OmegaConf.set_struct(cfg, False)
        overrides = OmegaConf.create(
            {
                "model": {
                    "path": self.spec.model,
                    "tokenizer_path": self.spec.model,
                    "trust_remote_code": False,
                    "external_lib": COMPATIBILITY_MODULE,
                    "enable_gradient_checkpointing": True,
                    "enable_activation_offload": self.offload,
                    "use_remove_padding": True,
                    "lora_rank": 8,
                    "lora_alpha": 16,
                    "target_modules": "all-linear",
                    "use_fused_kernels": True,
                    "fused_kernel_options": {"impl_backend": "torch"},
                    "lora": {"rank": 8, "alpha": 16, "dropout": 0.05},
                },
                "data": {
                    "train_batch_size": 1,
                    "micro_batch_size_per_gpu": 1,
                    "max_length": V4_MAX_LENGTH,
                    "max_token_len_per_gpu": 16_384,
                    "use_dynamic_bsz": False,
                    "messages_key": "messages",
                    "tools_key": "tools",
                    "exact_receipt_key": "exact_token_receipt",
                    "tokenizer_root": self.spec.model,
                    "tokenizer_id": "Qwen3.5-9B/local-frozen-chat-template",
                    "pad_mode": "no_padding",
                    "truncation": "error",
                    "num_workers": 0,
                    "shuffle": False,
                    "custom_cls": {
                        "path": CUSTOM_DATASET_PATH,
                        "name": CUSTOM_DATASET_NAME,
                    },
                    "rllm": {"tokenize_and_mask_method": "tool_aware_exact_final_decision"},
                },
                "engine": {
                    "strategy": "fsdp2",
                    "model_dtype": "bf16",
                    "dtype": "bfloat16",
                    "param_offload": self.offload,
                    "optimizer_offload": self.offload,
                    "offload_policy": False,
                    "reshard_after_forward": True,
                    "fsdp_size": 4,
                    "ulysses_sequence_parallel_size": 4,
                    "use_torch_compile": False,
                    "forward_only": False,
                },
                "optim": {
                    "lr": 1e-4,
                    "lr_scheduler_type": "constant",
                    "total_training_steps": 1,
                },
                "checkpoint": {"save_contents": [], "load_contents": []},
                "trainer": {
                    "total_epochs": 1,
                    "total_training_steps": 1,
                    "save_freq": -1,
                    "test_freq": -1,
                    "logger": ["console"],
                    "resume_mode": "disable",
                    "resume_from_path": None,
                    "nnodes": 1,
                    "n_gpus_per_node": 4,
                    "balance_batch": False,
                    "profile_interval": [-1, -1],
                },
            }
        )
        cfg = OmegaConf.merge(cfg, overrides)
        self._config = cfg
        assert_qualification_config(cfg, offload=self.offload)
        return cfg

    def prepare_data(self) -> None:
        cfg = self.config
        train_path = Path(self.workdir) / "train.parquet"
        write_tool_aware_parquet(self.inputs, train_path)
        cfg.data.train_files = str(train_path)
        cfg.data.val_files = None

    def fit(self) -> None:
        raise RuntimeError(
            "64K qualification backend forbids fit(); use the forward/backward probe entry"
        )


class VeriGymHweDecisionSft64kTrainer:
    """Dedicated dispatcher that can only prepare or launch a qualification probe."""

    def __init__(
        self,
        *,
        dataset_root: Path,
        model_root: Path,
        scratch_root: Path,
        offload: bool = False,
    ) -> None:
        inputs = load_tool_aware_v4_dataset(dataset_root)
        dataset = Dataset(data=list(inputs.rows), name="verigym_hwe_decision_sft_64k_v4")
        scratch = _new_scratch_directory(scratch_root, offload=offload)
        spec = SFTSpec(
            model=str(model_root.resolve(strict=True)),
            train_dataset=dataset,
            val_dataset=None,
            lr=1e-4,
            lr_schedule="constant",
            epochs=1,
            batch_size=1,
            max_length=V4_MAX_LENGTH,
            tokenize_method="hf_template",
            lora_rank=8,
            save_freq=-1,
            val_freq=-1,
            project="verigym-hwe-qualification",
            experiment="deepseek-decision-sft-64k-v4",
            output_dir=str(scratch),
        )
        self.backend = VeriGymHweDecisionSft64kBackend(
            spec,
            inputs=inputs,
            offload=offload,
        )

    def prepare(self) -> VeriGymHweDecisionSft64kBackend:
        self.backend.validate_spec()
        self.backend.build_config()
        self.backend.prepare_data()
        return self.backend

    def launch_qualification(
        self,
        *,
        report: Path,
        rllm_source: Path,
        verl_source: Path,
        transformers_source: Path,
    ) -> None:
        backend = self.prepare()
        config_path = backend.serialize_config()
        command = [
            sys.executable,
            "-m",
            "torch.distributed.run",
            "--standalone",
            "--nnodes=1",
            "--nproc_per_node=4",
            "-m",
            "verigym_training_reference.hwe_decision_sft_64k_entry",
            "--config",
            config_path,
            "--report",
            str(report),
            "--scratch-root",
            str(Path(backend.workdir).parent),
            "--rllm-source",
            str(rllm_source),
            "--verl-source",
            str(verl_source),
            "--transformers-source",
            str(transformers_source),
        ]
        environment = {**os.environ, "RLLM_SFT_IN_TORCHRUN": "1"}
        if environment.get("ROCR_VISIBLE_DEVICES") and environment.get("CUDA_VISIBLE_DEVICES"):
            environment.pop("ROCR_VISIBLE_DEVICES", None)
        result = subprocess.run(command, env=environment, check=False)
        if result.returncode != 0:
            raise SFTConfigError(f"64K qualification torchrun exited with code {result.returncode}")

    def train(self) -> None:
        raise RuntimeError("64K qualification dispatcher never starts training")


def assert_qualification_config(config: Any, *, offload: bool) -> None:
    """Verify the resolved config rather than trusting requested overrides."""

    expected = {
        "model.trust_remote_code": False,
        "model.external_lib": COMPATIBILITY_MODULE,
        "model.enable_gradient_checkpointing": True,
        "model.enable_activation_offload": offload,
        "model.use_remove_padding": True,
        "model.lora_rank": 8,
        "model.lora_alpha": 16,
        "model.use_fused_kernels": True,
        "model.fused_kernel_options.impl_backend": "torch",
        "data.train_batch_size": 1,
        "data.micro_batch_size_per_gpu": 1,
        "data.max_length": V4_MAX_LENGTH,
        "data.max_token_len_per_gpu": 16_384,
        "data.use_dynamic_bsz": False,
        "data.pad_mode": "no_padding",
        "data.truncation": "error",
        "data.num_workers": 0,
        "data.custom_cls.path": CUSTOM_DATASET_PATH,
        "data.custom_cls.name": CUSTOM_DATASET_NAME,
        "engine.strategy": "fsdp2",
        "engine.model_dtype": "bf16",
        "engine.dtype": "bfloat16",
        "engine.param_offload": offload,
        "engine.optimizer_offload": offload,
        "engine.ulysses_sequence_parallel_size": 4,
        "engine.use_torch_compile": False,
        "trainer.n_gpus_per_node": 4,
        "trainer.resume_mode": "disable",
        "trainer.save_freq": -1,
    }
    for path, value in expected.items():
        actual = OmegaConf.select(config, path)
        if actual != value:
            raise SFTConfigError(f"qualification config {path}={actual!r}; expected {value!r}")


def validate_qualification_runtime(
    *, rllm_source: Path, verl_source: Path, transformers_source: Path
) -> dict[str, str]:
    """Bind the interpreter to the frozen upstream source identities."""

    rllm_root = rllm_source.resolve(strict=True)
    verl_root = verl_source.resolve(strict=True)
    transformers_root = transformers_source.resolve(strict=True)
    if not rllm_root.is_dir() or not verl_root.is_dir() or not transformers_root.is_dir():
        raise SFTConfigError("qualification source bindings must be directories")
    rllm_commit = _source_commit(rllm_root, marker=".verigym-rllm-commit")
    verl_commit = _source_commit(verl_root, marker=".verigym-verl-commit")
    transformers_commit = _source_commit(
        transformers_root,
        marker=".verigym-transformers-commit",
    )
    verl_version = importlib.metadata.version("verl")
    if rllm_commit != RLLM_COMMIT or transformers_commit != TRANSFORMERS_COMMIT:
        raise SFTConfigError("qualification rLLM, Transformers, or veRL pin changed")
    if verl_commit != VERL_COMMIT or verl_version != VERL_PACKAGE_VERSION:
        raise SFTConfigError("qualification veRL v0.8.0 source or package metadata changed")
    import rllm as rllm_package  # type: ignore[import-not-found]
    import transformers as transformers_package
    from transformers.models.qwen3_5.modeling_qwen3_5 import (  # type: ignore[import-not-found]
        Qwen3_5ForCausalLM,
    )

    imported_rllm = Path(rllm_package.__file__).resolve()
    imported_transformers = Path(transformers_package.__file__).resolve()
    if not imported_rllm.is_relative_to(rllm_root) or not imported_transformers.is_relative_to(
        transformers_root
    ):
        raise SFTConfigError("qualification interpreter did not import its bound source trees")
    if Qwen3_5ForCausalLM.__name__ != "Qwen3_5ForCausalLM":
        raise SFTConfigError("official Qwen3.5 causal-LM class is unavailable")
    return {
        "rllm_commit": rllm_commit,
        "verl_release_tag": f"v{VERL_VERSION}",
        "verl_commit": verl_commit,
        "verl_package_version": verl_version,
        "transformers_commit": transformers_commit,
        "rllm_import_root": str(rllm_root),
        "verl_source_root": str(verl_root),
        "transformers_import_root": str(transformers_root),
    }


def _source_commit(source: Path, *, marker: str) -> str:
    marker_path = source / marker
    if marker_path.is_file() and not marker_path.is_symlink():
        value = marker_path.read_text(encoding="ascii").strip()
    else:
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
            raise SFTConfigError(f"cannot identify frozen source tree {source.name}") from exc
        value = result.stdout.strip()
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise SFTConfigError(f"invalid source commit binding for {source.name}")
    return value


def _new_scratch_directory(root: Path, *, offload: bool) -> Path:
    if root.is_symlink():
        raise ValueError("64K qualification scratch root cannot be a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = root / ("offload" if offload else "primary")
    if destination.exists() or destination.is_symlink():
        raise ValueError("64K qualification scratch profile already exists")
    destination.mkdir(mode=0o700)
    return destination


__all__ = [
    "COMPATIBILITY_MODULE",
    "CUSTOM_DATASET_NAME",
    "CUSTOM_DATASET_PATH",
    "RLLM_COMMIT",
    "TRANSFORMERS_COMMIT",
    "VERL_COMMIT",
    "VERL_PACKAGE_VERSION",
    "VERL_VERSION",
    "VeriGymHweDecisionSft64kBackend",
    "VeriGymHweDecisionSft64kTrainer",
    "assert_qualification_config",
    "validate_qualification_runtime",
]
