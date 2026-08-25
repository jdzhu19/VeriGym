"""veRL 0.8.0 FSDP compatibility hooks for the frozen BF16 SFT LoRA.

veRL 0.8.0 exposes dropout in its Megatron LoRA subtree, but its Hugging Face
FSDP engine constructs ``peft.LoraConfig`` without forwarding a dropout value.
PEFT also defaults to promoting BF16 adapter weights to FP32, which gives an
FSDP2 wrap group mixed original parameter dtypes when the base model is BF16.
The frozen VeriGym run imports this module through ``model.external_lib`` before
the engine builds the PEFT model. Keep both hooks narrowly version-bound and
fail if another caller tries to supply a conflicting value.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

LORA_DROPOUT = 0.05
_PATCH_MARKER = "__verigym_lora_dropout__"
_DTYPE_PATCH_MARKER = "__verigym_bf16_adapter_dtype__"


def wrap_lora_config(factory: Callable[..., Any]) -> Callable[..., Any]:
    """Return a factory that injects the frozen dropout without hiding conflicts."""

    if getattr(factory, _PATCH_MARKER, None) == LORA_DROPOUT:
        return factory

    def configured_lora(*args: Any, **kwargs: Any) -> Any:
        supplied = float(kwargs.get("lora_dropout", LORA_DROPOUT))
        if supplied != LORA_DROPOUT:
            raise RuntimeError(f"VeriGym requires lora_dropout={LORA_DROPOUT}; received {supplied}")
        kwargs["lora_dropout"] = LORA_DROPOUT
        return factory(*args, **kwargs)

    setattr(configured_lora, _PATCH_MARKER, LORA_DROPOUT)
    return configured_lora


def wrap_get_peft_model(factory: Callable[..., Any]) -> Callable[..., Any]:
    """Disable PEFT's default BF16-to-FP32 adapter promotion for FSDP2."""

    if getattr(factory, _DTYPE_PATCH_MARKER, False):
        return factory

    def configured_peft(*args: Any, **kwargs: Any) -> Any:
        if len(args) >= 5:
            if args[4] is not False:
                raise RuntimeError("VeriGym BF16 FSDP2 requires autocast_adapter_dtype=False")
        else:
            supplied = kwargs.get("autocast_adapter_dtype", False)
            if supplied is not False:
                raise RuntimeError("VeriGym BF16 FSDP2 requires autocast_adapter_dtype=False")
            kwargs["autocast_adapter_dtype"] = False
        return factory(*args, **kwargs)

    setattr(configured_peft, _DTYPE_PATCH_MARKER, True)
    return configured_peft


def install_verl_lora_dropout() -> None:
    """Patch only veRL's FSDP PEFT construction site."""

    from verl.workers.engine.fsdp import transformer_impl  # type: ignore[import-not-found]

    transformer_impl.LoraConfig = wrap_lora_config(transformer_impl.LoraConfig)
    transformer_impl.get_peft_model = wrap_get_peft_model(transformer_impl.get_peft_model)


try:
    install_verl_lora_dropout()
except ModuleNotFoundError as exc:
    # Ordinary credential-free VeriGym tests do not install the GPU training stack.
    # In the opt-in training path the runtime pin check requires veRL before this
    # module is handed to ``model.external_lib``.
    if exc.name is None or not exc.name.startswith("verl"):
        raise
