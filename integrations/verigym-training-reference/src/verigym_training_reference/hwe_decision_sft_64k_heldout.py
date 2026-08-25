"""Native Qwen3.5 base/LoRA agent for one frozen HWE heldout replay."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.deepseek_harness import deepseek_harness_tool_definitions
from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    AgentAction,
    AgentAdapter,
    AgentContext,
    AgentDescriptor,
    AgentPromptPolicySpec,
    AgentTerminationError,
    EpisodeFailure,
    EpisodeResult,
    ExternalAgentAccounting,
    ExternalAgentBridge,
    FinalSubmissionAction,
    InteractionMode,
    Observation,
    TerminationReason,
    validate_prompt_text,
)
from verigym_deepseek_harness.agent import (
    BASE_INSTRUCTION_POLICY_V3,
    PROMPT_CONTRACT_ID_V3,
    PROMPT_CONTRACT_VERSION_V3,
    _system_prompt_v3,
    _task_prompt,
)
from verigym_deepseek_harness.broker import (
    DeepSeekHarnessHweBroker,
    broker_stats_dict,
)

from .hwe_decision_sft_64k_native_inference import (
    _load_model,
    _load_model_sharded,
    parse_qwen_tool_calls,
)

_MAX_CONTEXT_TOKENS = 65_536
_EXPECTED_SEED = 484
_RECOVERABLE_BROKER_ERRORS = {"invalid_arguments"}
_SHARDED_GPU_COUNT = 4
_SHARDED_MAX_MEMORY_BYTES = 20 * 1024**3


class ModelDecisionError(RuntimeError):
    """The local policy emitted a decision outside the frozen public contract."""


def parse_qwen_assistant_decision(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Return public prefix text and typed calls, rejecting interleaved/suffix prose."""

    from .hwe_decision_sft_64k_native_inference import _TOOL_CALL

    matches = list(_TOOL_CALL.finditer(text))
    calls = parse_qwen_tool_calls(text)
    if not matches or not calls:
        raise ModelDecisionError("Qwen generation did not contain a typed HWE tool call")
    cursor = matches[0].end()
    for match in matches[1:]:
        if text[cursor : match.start()].strip():
            raise ModelDecisionError("Qwen generation interleaved prose between sibling calls")
        cursor = match.end()
    public_text = text[: matches[0].start()].strip()
    if "<think" in public_text.lower() or "</think" in public_text.lower():
        raise ModelDecisionError("Qwen generation exposed a forbidden private-thinking block")
    if any(call["name"] == "finish" for call in calls[:-1]):
        raise ModelDecisionError("Qwen generation placed finish before another sibling call")
    return public_text, calls


def adapter_artifact_inventory(root: Path) -> tuple[list[dict[str, Any]], str]:
    """Hash the compact adapter without following links or accepting extra object types."""

    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("heldout adapter root is unsafe")
    values: list[dict[str, Any]] = []
    for path in sorted(resolved.rglob("*")):
        if path.is_symlink():
            raise ValueError("heldout adapter contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("heldout adapter contains a special file")
        values.append(
            {
                "path": path.relative_to(resolved).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    if {item["path"] for item in values} != {
        "adapter_config.json",
        "adapter_model.safetensors",
    }:
        raise ValueError("heldout adapter inventory differs from the compact LoRA artifact")
    aggregate = hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return values, aggregate


class Qwen35HweHeldoutAgentAdapter(AgentAdapter):
    """Run one deterministic model-loaded episode through the exact six-tool broker."""

    requires_model = False
    prompt_policy_spec = AgentPromptPolicySpec(
        prompt_contract_id=PROMPT_CONTRACT_ID_V3,
        prompt_contract_version=PROMPT_CONTRACT_VERSION_V3,
        task_context_policy="hwe_bounded_repository_context_v2",
        base_instruction_policy=BASE_INSTRUCTION_POLICY_V3,
        content_visibility_policy="public_task_workspace_no_hidden_reference_v1",
        max_prompt_bytes=2 * 1024 * 1024,
        max_task_context_bytes=1024 * 1024,
        versioned_context_allowed=False,
    )
    supported_modes = frozenset({InteractionMode.AGENT})
    descriptor = AgentDescriptor(
        schema_version=SCHEMA_VERSION,
        name="deepseek-harness-qwen35-heldout-agent-v1",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="local-qwen35",
        capabilities=[
            "external_coding_agent",
            "workspace_editing",
            "machine_readable_events",
            "local_gpu_inference",
            "heldout_development_canary",
        ],
    )

    def __init__(
        self,
        *,
        model_root: Path,
        adapter_root: Path,
        control_root: Path,
        authorization_hash: str,
        adapter_artifact_hash: str,
    ) -> None:
        self._bound_model_root = model_root
        self._bound_adapter_root = adapter_root
        self._bound_control_root = control_root
        self._bound_authorization_hash = authorization_hash
        self._bound_adapter_artifact_hash = adapter_artifact_hash
        self._context: AgentContext | None = None
        self._bridge: ExternalAgentBridge | None = None
        self._policy: str | None = None
        self._model_root: Path | None = None
        self._adapter_root: Path | None = None
        self._authorization_hash: str | None = None
        self._adapter_artifact_hash: str | None = None
        self._control_root: Path | None = None
        self._system_prompt: str | None = None
        self._task_prompt: str | None = None
        self._tools: list[dict[str, Any]] = []
        self._max_decisions = 0
        self._max_new_tokens = 0
        self._launched = False
        self._evidence_path: Path | None = None
        self._runtime_stage = "not_started"
        self._model_generate_calls = 0
        self._inference_gpu_count = 1
        self._episode_started: float | None = None
        self._completed_decisions = 0
        self._last_prompt_token_count = 0

    def start(self, context: AgentContext) -> None:
        bridge = context.external_bridge
        if bridge is None or bridge.execution_backend != "docker_outer_runtime_delegated":
            raise ValueError("Qwen heldout HWE requires the Docker outer runtime")
        if bridge.isolation_level != "docker_standard":
            raise ValueError("Qwen heldout HWE requires Docker standard isolation")
        if (
            context.prompt_policy is None
            or context.prompt_policy.id != self.prompt_policy_spec.prompt_contract_id
            or context.prompt_policy.version != self.prompt_policy_spec.prompt_contract_version
        ):
            raise ValueError("Qwen heldout HWE prompt contract is not frozen")
        if context.seed != _EXPECTED_SEED:
            raise ValueError("Qwen heldout HWE seed changed")
        options = context.agent_options
        policy = options.get("policy")
        if policy not in {"base", "adapter"}:
            raise ValueError("Qwen heldout HWE policy must be base or adapter")
        model_root = _safe_directory(self._bound_model_root, label="model root")
        bound_adapter_root = _safe_directory(self._bound_adapter_root, label="adapter root")
        adapter_root = bound_adapter_root if policy == "adapter" else None
        authorization_hash = _sha256_option(options, "execution_binding_sha256")
        expected_adapter_hash = _sha256_option(options, "adapter_artifact_hash")
        if authorization_hash != self._bound_authorization_hash:
            raise ValueError("Qwen heldout authorization identity changed")
        if expected_adapter_hash != self._bound_adapter_artifact_hash:
            raise ValueError("Qwen heldout adapter binding changed")
        _inventory, observed_adapter_hash = adapter_artifact_inventory(bound_adapter_root)
        if observed_adapter_hash != expected_adapter_hash:
            raise ValueError("Qwen heldout adapter artifact identity changed")
        max_decisions = options.get("max_decisions")
        max_new_tokens = options.get("max_output_tokens")
        if max_decisions != 200 or max_new_tokens != 256:
            raise ValueError("Qwen heldout generation bounds changed")
        inference_gpu_count = options.get("inference_gpu_count", 1)
        if inference_gpu_count not in {1, _SHARDED_GPU_COUNT}:
            raise ValueError("Qwen heldout inference GPU count is unsupported")
        if (
            inference_gpu_count == _SHARDED_GPU_COUNT
            and options.get("max_memory_per_gpu_bytes") != _SHARDED_MAX_MEMORY_BYTES
        ):
            raise ValueError("Qwen heldout sharded memory bound changed")
        control_root = self._bound_control_root
        if not control_root.is_absolute() or control_root.is_symlink():
            raise ValueError("Qwen heldout control root is unsafe")
        control_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        system_prompt = _system_prompt_v3()
        task_prompt = validate_prompt_text(_task_prompt(context, bridge), context.prompt_policy)
        tools = deepseek_harness_tool_definitions()
        self._context = context
        self._bridge = bridge
        self._policy = str(policy)
        self._model_root = model_root
        self._adapter_root = adapter_root
        self._authorization_hash = authorization_hash
        self._adapter_artifact_hash = expected_adapter_hash
        self._control_root = control_root
        self._system_prompt = system_prompt
        self._task_prompt = task_prompt
        self._tools = tools
        self._max_decisions = int(max_decisions)
        self._max_new_tokens = int(max_new_tokens)
        self._launched = False
        self._evidence_path = bridge.artifact_root / "heldout-native-inference.json"
        self._runtime_stage = "started"
        self._model_generate_calls = 0
        self._inference_gpu_count = int(inference_gpu_count)
        self._episode_started = None
        self._completed_decisions = 0
        self._last_prompt_token_count = 0
        bridge.emit_event(
            "deepseek_harness_qwen35_heldout_prompt_policy_bound",
            {
                "authorization_hash": authorization_hash,
                "policy": str(policy),
                "prompt_policy_hash": context.prompt_policy.configuration_fingerprint,
                "heldout_transcript_loaded": False,
            },
        )

    def act(self, observation: Observation) -> AgentAction:
        del observation
        if self._launched:
            raise _termination(
                "multiple_local_model_episodes",
                "Qwen heldout adapter attempted more than one episode",
                infrastructure=False,
            )
        self._launched = True
        try:
            evidence = self._run_model_episode()
        except ModelDecisionError as exc:
            self._write_failure_evidence(exc, infrastructure=False)
            raise _termination("qwen_action_policy", str(exc), infrastructure=False) from exc
        except AgentTerminationError:
            raise
        except Exception as exc:
            self._write_failure_evidence(exc, infrastructure=True)
            raise _termination(
                "qwen_native_inference_runtime",
                f"Qwen native heldout inference failed: {type(exc).__name__}",
                infrastructure=True,
            ) from exc
        assert self._evidence_path is not None
        atomic_dump_json(self._evidence_path, evidence)
        return FinalSubmissionAction(
            message="Qwen3.5 submitted one heldout candidate to the ordinary VeriGym verifier."
        )

    def finish(self, result: EpisodeResult) -> None:
        path = self._evidence_path
        if path is None or path.is_symlink() or not path.is_file():
            return
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Qwen heldout evidence is malformed")
        value.pop("evidence_hash", None)
        value.update(
            {
                "ordinary_verifier_resolved": result.resolved,
                "ordinary_termination_reason": result.termination_reason,
                "model_called_during_finish": False,
                "candidate_modified_during_finish": False,
            }
        )
        value["evidence_hash"] = content_hash(value)
        atomic_dump_json(path, value)

    def _write_failure_evidence(self, error: Exception, *, infrastructure: bool) -> None:
        path = self._evidence_path
        if path is None or self._context is None or self._policy is None:
            return
        raw_message = str(error)
        sanitized = re.sub(
            r"(?<![A-Za-z0-9_])/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+",
            "<path>",
            raw_message,
        )[:1000]
        base: dict[str, Any] = {
            "schema_version": "1.0",
            "format_id": "verigym_hwe_qwen35_64k_heldout_native_failure_v1",
            "status": "infrastructure_invalid" if infrastructure else "policy_rejected",
            "task_id": self._context.task.id,
            "policy": self._policy,
            "authorization_hash": self._authorization_hash,
            "runtime_stage": self._runtime_stage,
            "failure_type": type(error).__name__,
            "failure_message_sanitized": sanitized,
            "failure_message_sha256": hashlib.sha256(raw_message.encode()).hexdigest(),
            "model_generate_calls": self._model_generate_calls,
            "completed_decisions": self._completed_decisions,
            "last_prompt_token_count": self._last_prompt_token_count,
            "inference_gpu_count": self._inference_gpu_count,
            "heldout_transcript_loaded": False,
            "training_dataset_loaded": False,
            "reference_solution_loaded": False,
            "hidden_verifier_assets_loaded": False,
            "raw_model_text_persisted": False,
            "optimizer_steps": 0,
            "checkpoint_written": False,
            "benchmark_score_claimed": False,
        }
        if self._episode_started is not None:
            base["wall_seconds"] = time.monotonic() - self._episode_started
        try:
            import torch  # type: ignore[import-not-found]

            peaks = [
                int(torch.cuda.max_memory_allocated(index))
                for index in range(torch.cuda.device_count())
            ]
            reserves = [
                int(torch.cuda.max_memory_reserved(index))
                for index in range(torch.cuda.device_count())
            ]
            base["peak_memory_allocated_bytes"] = max(peaks, default=0)
            base["peak_memory_reserved_bytes"] = max(reserves, default=0)
            base["per_gpu_peak_memory_allocated_bytes"] = peaks
            base["per_gpu_peak_memory_reserved_bytes"] = reserves
        except Exception:
            pass
        atomic_dump_json(path, {**base, "evidence_hash": content_hash(base)})

    def _run_model_episode(self) -> dict[str, Any]:
        import torch
        from transformers import AutoTokenizer

        context, bridge, policy, model_root, adapter_root = self._configured()
        expected_cuda_devices = "0" if self._inference_gpu_count == 1 else "0,1,2,3"
        if os.environ.get("CUDA_VISIBLE_DEVICES") != expected_cuda_devices:
            raise RuntimeError("Qwen heldout episode CUDA device binding changed")
        self._runtime_stage = "tokenizer_load"
        tokenizer = AutoTokenizer.from_pretrained(  # type: ignore[no-untyped-call]
            model_root,
            local_files_only=True,
            trust_remote_code=False,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": self._task_prompt},
        ]
        decisions: list[dict[str, Any]] = []
        input_tokens = 0
        output_tokens = 0
        max_prompt_tokens = 0
        torch.manual_seed(_EXPECTED_SEED)
        torch.cuda.manual_seed_all(_EXPECTED_SEED)
        torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()
        self._episode_started = started
        model: Any | None = None
        broker: DeepSeekHarnessHweBroker | None = None
        stats: dict[str, Any] | None = None
        try:
            self._runtime_stage = "model_load"
            if self._inference_gpu_count == _SHARDED_GPU_COUNT:
                model = _load_model_sharded(
                    model_root,
                    adapter_root,
                    gpu_count=_SHARDED_GPU_COUNT,
                    max_memory_per_gpu_bytes=_SHARDED_MAX_MEMORY_BYTES,
                )
            else:
                model = _load_model(model_root, adapter_root, device="cuda:0")
            assert self._control_root is not None
            with tempfile.TemporaryDirectory(prefix="heldout-", dir=self._control_root) as raw:
                broker = DeepSeekHarnessHweBroker(
                    bridge=bridge,
                    socket_path=Path(raw) / "broker.sock",
                    private_audit_root=bridge.artifact_root.parent.parent,
                )
                for decision_index in range(self._max_decisions):
                    self._runtime_stage = f"decision_{decision_index + 1}_generation"
                    self._model_generate_calls += 1
                    generated = _generate_decision(
                        model=model,
                        tokenizer=tokenizer,
                        messages=messages,
                        tools=self._tools,
                        max_new_tokens=self._max_new_tokens,
                    )
                    input_tokens += generated["prompt_token_count"]
                    output_tokens += generated["generated_token_count"]
                    max_prompt_tokens = max(max_prompt_tokens, generated["prompt_token_count"])
                    self._last_prompt_token_count = generated["prompt_token_count"]
                    self._runtime_stage = f"decision_{decision_index + 1}_parse"
                    public_text, calls = parse_qwen_assistant_decision(generated["text"])
                    call_messages: list[dict[str, Any]] = []
                    for sibling_index, call in enumerate(calls):
                        call_id = f"qwen-{decision_index + 1}-{sibling_index + 1}"
                        call_messages.append(
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": call["arguments"],
                                },
                            }
                        )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": public_text,
                            "tool_calls": call_messages,
                        }
                    )
                    response_hashes: list[str] = []
                    for call_message in call_messages:
                        function = call_message["function"]
                        self._runtime_stage = (
                            f"decision_{decision_index + 1}_broker_{function['name']}"
                        )
                        response = broker._dispatch(  # noqa: SLF001
                            {
                                "id": call_message["id"],
                                "name": function["name"],
                                "arguments": function["arguments"],
                            }
                        )
                        error = response.get("error")
                        if (
                            response.get("ok") is not True
                            and error not in _RECOVERABLE_BROKER_ERRORS
                        ):
                            if error == "infrastructure_failure":
                                raise RuntimeError("HWE broker reported an infrastructure failure")
                            raise ModelDecisionError(
                                f"Qwen tool call was rejected by the HWE broker: {error}"
                            )
                        response_text = str(response.get("text", ""))
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_message["id"],
                                "name": function["name"],
                                "content": response_text,
                            }
                        )
                        response_hashes.append(hashlib.sha256(response_text.encode()).hexdigest())
                    decisions.append(
                        {
                            "decision_index": decision_index,
                            "prompt_token_count": generated["prompt_token_count"],
                            "generated_token_count": generated["generated_token_count"],
                            "generated_ids_sha256": generated["generated_ids_sha256"],
                            "generated_text_sha256": hashlib.sha256(
                                generated["text"].encode()
                            ).hexdigest(),
                            "public_text_present": bool(public_text),
                            "tool_names": [call["name"] for call in calls],
                            "tool_response_sha256": response_hashes,
                        }
                    )
                    self._completed_decisions = len(decisions)
                    if calls[-1]["name"] == "finish":
                        break
                else:
                    raise ModelDecisionError("Qwen heldout episode reached its decision limit")
                broker.stop()
                stats = broker_stats_dict(broker.stats())
                broker = None
                self._runtime_stage = "model_episode_completed"
        finally:
            if broker is not None:
                broker.stop()
            del model
            gc.collect()
            for device_index in range(torch.cuda.device_count()):
                with torch.cuda.device(device_index):
                    torch.cuda.empty_cache()
        if stats is None or stats.get("finished") is not True:
            raise ModelDecisionError("Qwen heldout episode lacks an explicit finish action")
        rejection_codes = set(stats.get("rejection_codes", []))
        if rejection_codes - _RECOVERABLE_BROKER_ERRORS:
            raise ModelDecisionError("Qwen heldout episode contains a non-recoverable rejection")
        duration = time.monotonic() - started
        bridge.record_accounting(
            ExternalAgentAccounting(
                process_wall_time_s=duration,
                cli_event_count=len(decisions),
                model_call_count=len(decisions),
                external_tool_call_count=int(stats["tool_calls"]),
                external_command_count=int(stats["command_calls"]),
                public_test_invocation_count=0,
                external_file_read_count=int(stats["file_reads"]),
                external_file_write_count=int(stats["patches"]),
                external_patch_count=int(stats["patches"]),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
        )
        allocated_peaks = [
            int(torch.cuda.max_memory_allocated(index))
            for index in range(torch.cuda.device_count())
        ]
        reserved_peaks = [
            int(torch.cuda.max_memory_reserved(index)) for index in range(torch.cuda.device_count())
        ]
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_hwe_qwen35_64k_heldout_native_episode_v1",
            "status": "model_episode_completed",
            "task_id": context.task.id,
            "policy": policy,
            "seed": _EXPECTED_SEED,
            "authorization_hash": self._authorization_hash,
            "adapter_artifact_hash": self._adapter_artifact_hash,
            "adapter_loaded": adapter_root is not None,
            "independent_model_reload": True,
            "inference_gpu_count": self._inference_gpu_count,
            "model_parallelism": (
                "balanced_layer_sharding"
                if self._inference_gpu_count == _SHARDED_GPU_COUNT
                else "single_gpu"
            ),
            "max_memory_per_gpu_bytes": (
                _SHARDED_MAX_MEMORY_BYTES
                if self._inference_gpu_count == _SHARDED_GPU_COUNT
                else None
            ),
            "trust_remote_code": False,
            "dtype": "bfloat16",
            "temperature": 0,
            "do_sample": False,
            "max_context_tokens": _MAX_CONTEXT_TOKENS,
            "max_new_tokens_per_decision": self._max_new_tokens,
            "decision_count": len(decisions),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "max_prompt_token_count": max_prompt_tokens,
            "decisions": decisions,
            "broker": stats,
            "tool_schema_hash": content_hash(self._tools),
            "system_prompt_sha256": hashlib.sha256(str(self._system_prompt).encode()).hexdigest(),
            "task_prompt_sha256": hashlib.sha256(str(self._task_prompt).encode()).hexdigest(),
            "heldout_transcript_loaded": False,
            "training_dataset_loaded": False,
            "reference_solution_loaded": False,
            "hidden_verifier_assets_loaded": False,
            "raw_model_text_persisted": False,
            "optimizer_steps": 0,
            "checkpoint_written": False,
            "benchmark_score_claimed": False,
            "quality_improvement_claimed": False,
            "peak_memory_allocated_bytes": max(allocated_peaks, default=0),
            "peak_memory_reserved_bytes": max(reserved_peaks, default=0),
            "per_gpu_peak_memory_allocated_bytes": allocated_peaks,
            "per_gpu_peak_memory_reserved_bytes": reserved_peaks,
            "wall_seconds": duration,
        }
        return {**base, "evidence_hash": content_hash(base)}

    def _configured(
        self,
    ) -> tuple[AgentContext, ExternalAgentBridge, str, Path, Path | None]:
        if (
            self._context is None
            or self._bridge is None
            or self._policy is None
            or self._model_root is None
            or self._system_prompt is None
            or self._task_prompt is None
        ):
            raise RuntimeError("Qwen heldout agent has not been started")
        return (
            self._context,
            self._bridge,
            self._policy,
            self._model_root,
            self._adapter_root,
        )


def _generate_decision(
    *,
    model: Any,
    tokenizer: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_new_tokens: int,
) -> dict[str, Any]:
    import torch

    encoded = tokenizer.apply_chat_template(
        messages,
        tools=tools,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    prompt_ids = encoded.get("input_ids") if isinstance(encoded, Mapping) else encoded
    if (
        not isinstance(prompt_ids, list)
        or not prompt_ids
        or not all(isinstance(value, int) for value in prompt_ids)
    ):
        raise RuntimeError("Qwen heldout tokenizer returned malformed input IDs")
    if len(prompt_ids) > _MAX_CONTEXT_TOKENS:
        raise ModelDecisionError("Qwen heldout public context exceeded 65,536 tokens")
    input_device = model.get_input_embeddings().weight.device
    input_ids = torch.tensor([prompt_ids], dtype=torch.long, device=input_device)
    with torch.inference_mode():
        generated = model.generate(
            input_ids=input_ids,
            do_sample=False,
            max_new_tokens=max_new_tokens,
            use_cache=True,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    for device_index in range(torch.cuda.device_count()):
        torch.cuda.synchronize(device_index)
    new_ids = generated[0, input_ids.shape[1] :].tolist()
    text = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
    result = {
        "prompt_token_count": len(prompt_ids),
        "generated_token_count": len(new_ids),
        "generated_ids_sha256": hashlib.sha256(
            b"".join(int(value).to_bytes(4, "big") for value in new_ids)
        ).hexdigest(),
        "text": text,
    }
    del input_ids, generated
    for device_index in range(torch.cuda.device_count()):
        with torch.cuda.device(device_index):
            torch.cuda.empty_cache()
    return result


def _safe_directory(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.resolve(strict=True).is_dir():
        raise ValueError(f"Qwen heldout {label} is unsafe")
    return path.resolve(strict=True)


def _sha256_option(options: Mapping[str, Any], key: str) -> str:
    value = options.get(key)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"Qwen heldout option {key} is not a SHA-256 identity")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _termination(category: str, message: str, *, infrastructure: bool) -> AgentTerminationError:
    return AgentTerminationError(
        TerminationReason.RUNTIME_ERROR if infrastructure else TerminationReason.POLICY_VIOLATION,
        EpisodeFailure(
            kind="runtime" if infrastructure else "policy",
            category=category,
            message=message,
            infrastructure=infrastructure,
        ),
    )


__all__ = [
    "ModelDecisionError",
    "Qwen35HweHeldoutAgentAdapter",
    "adapter_artifact_inventory",
    "parse_qwen_assistant_decision",
]
