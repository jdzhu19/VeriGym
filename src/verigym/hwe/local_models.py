"""Optional local Transformers adapters for the frozen Qwen/CoACT gates.

Importing this module does not import torch or Transformers.  The training-ready scripts must
explicitly provide local model directories and both adapters use ``local_files_only`` and
``trust_remote_code=False``.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import signal
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from verigym.core.hashing import content_hash
from verigym.hwe.profiles import hwe_tool_definitions


class LocalModelUnavailable(RuntimeError):
    """Raised when optional local inference dependencies or files are unavailable."""


class LocalQwenActionPredictor:
    """Decode typed HWE action JSON with a local Qwen3.5 checkpoint."""

    def __init__(self, model_root: Path, *, device: str = "cuda:0") -> None:
        runtime_device, shard_count = _prepare_device_group(device)
        torch, transformers = _imports()
        self._torch = torch
        self._device = runtime_device
        self._action_cache: dict[tuple[str, float, int], str] = {}
        root = _safe_model_root(model_root)
        self._tokenizer = transformers.AutoTokenizer.from_pretrained(
            str(root), local_files_only=True, trust_remote_code=False
        )
        model_kwargs: dict[str, Any] = {
            "local_files_only": True,
            "trust_remote_code": False,
            "dtype": torch.bfloat16,
        }
        if shard_count == 1:
            model_kwargs["device_map"] = {"": runtime_device}
        else:
            model_kwargs["device_map"] = "balanced"
            model_kwargs["max_memory"] = {index: "22GiB" for index in range(shard_count)}
        # HWE prompts are text-only.  Loading the causal-LM class avoids placing Qwen's unused
        # vision tower on every NAP worker, leaving room for long-reference activations.
        self._model = transformers.AutoModelForCausalLM.from_pretrained(str(root), **model_kwargs)
        self._model.eval()

    def predict_action(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float,
        seed: int,
    ) -> str:
        torch = self._torch
        cache_key = (content_hash(list(messages)), temperature, seed)
        cached = self._action_cache.get(cache_key)
        if cached is not None:
            return cached
        prompt_messages = _qwen_messages(messages)
        prompt_messages.append(
            {
                "role": "user",
                "content": (
                    "Return only one JSON object with fields action and arguments for the next "
                    "HWE native-shell tool call. Do not explain your choice."
                ),
            }
        )
        inputs = self._tokenizer.apply_chat_template(
            prompt_messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
            tools=hwe_tool_definitions(profile_id="hwe_standard_v2"),
            enable_thinking=False,
        )
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        # Qwen3.5-9B nearly fills a 24-GiB A30 at bf16.  Qwen's XML tool dialect still needs
        # room for closing tags and a bounded shell command, so keep a modest output budget.
        kwargs: dict[str, Any] = {
            "max_new_tokens": 96,
            "do_sample": temperature > 0,
            # Qwen sometimes emits the function close but not the optional outer wrapper before
            # the bounded decode reaches its budget.  The NAP parser accepts that dialect, so
            # stop at either close tag and avoid spending long-context decode steps on padding.
            "stop_strings": ["</tool_call>", "</function>"],
            "tokenizer": self._tokenizer,
            # Qwen3.5's causal-LM forward defaults to returning logits for every prefill token.
            # Generation only needs the final position; keeping this explicit avoids allocating
            # an 83K x 248K vocabulary tensor on the long HWE reference histories.
            "logits_to_keep": 1,
        }
        if temperature > 0:
            kwargs["temperature"] = temperature
            kwargs["top_p"] = 0.95
        with _seed_context(torch, self._device, seed):
            with torch.inference_mode():
                output = self._model.generate(**inputs, **kwargs)
        prompt_length = int(inputs["input_ids"].shape[-1])
        result = cast(
            str,
            self._tokenizer.decode(output[0][prompt_length:], skip_special_tokens=True),
        ).strip()
        self._action_cache[cache_key] = result
        return result

    def close(self) -> None:
        """Release the local model before an adaptive mode switch."""

        self._model = None
        self._tokenizer = None
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()


class ParallelLocalQwenActionPredictor:
    """Run identical frozen Qwen replicas in parallel for the eight NAP samples.

    A device entry may be a ``+``-joined group such as ``cuda:0+cuda:1``.  Each group hosts one
    balanced, text-only Qwen replica; this is required for HWE reference histories that exceed
    the memory budget of a single 24-GiB card.
    """

    def __init__(self, model_root: Path, *, devices: Sequence[str]) -> None:
        if not devices or len(set(devices)) != len(devices):
            raise LocalModelUnavailable("parallel Qwen NAP requires distinct devices")
        groups = tuple(_parse_device_group(device) for device in devices)
        flattened = tuple(item for group in groups for item in group)
        if len(set(flattened)) != len(flattened):
            raise LocalModelUnavailable("parallel Qwen NAP device groups must not overlap")
        self._direct_predictor: LocalQwenActionPredictor | None = None
        if len(devices) == 1:
            # A single balanced multi-card model is reliable in-process.  Keeping it out of a
            # one-worker spawn pool avoids a long-context CUDA/ProcessPool deadlock observed on
            # the HWE reference host, while multi-replica short requests remain parallel.
            self._direct_predictor = LocalQwenActionPredictor(model_root, device=devices[0])
            self._executors: tuple[ProcessPoolExecutor, ...] = ()
        else:
            context = multiprocessing.get_context("spawn")
            self._executors = tuple(
                ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=context,
                    initializer=_initialize_qwen_worker,
                    initargs=(str(model_root), device),
                )
                for device in devices
            )

    def predict_action(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float,
        seed: int,
    ) -> str:
        return self.predict_actions([messages], temperatures=[temperature], seeds=[seed])[0]

    def predict_actions(
        self,
        messages: Sequence[Sequence[Mapping[str, Any]]],
        *,
        temperatures: Sequence[float],
        seeds: Sequence[int],
    ) -> list[str]:
        if not len(messages) == len(temperatures) == len(seeds):
            raise ValueError("parallel Qwen NAP request lengths differ")
        if self._direct_predictor is not None:
            return [
                self._direct_predictor.predict_action(
                    context,
                    temperature=temperature,
                    seed=seed,
                )
                for context, temperature, seed in zip(messages, temperatures, seeds, strict=True)
            ]
        futures = [
            self._executors[index % len(self._executors)].submit(
                _predict_qwen_worker,
                ([dict(message) for message in context], temperature, seed),
            )
            for index, (context, temperature, seed) in enumerate(
                zip(messages, temperatures, seeds, strict=True)
            )
        ]
        return [future.result() for future in futures]

    def close(self) -> None:
        if self._direct_predictor is not None:
            self._direct_predictor.close()
            self._direct_predictor = None
        for executor in self._executors:
            executor.shutdown(wait=True, cancel_futures=True)


class SubprocessLocalQwenActionPredictor:
    """Keep one balanced long-context model in a fresh Python/CUDA process.

    A long-context model is intentionally isolated from the seven short-context replica workers.
    The worker uses a newline-delimited JSON protocol, so a CUDA context created by the replicas
    cannot leak into the sharded model during an adaptive mode switch.
    """

    def __init__(self, model_root: Path, *, device: str) -> None:
        command = [
            sys.executable,
            "-m",
            "verigym.hwe.local_models",
            "--hwe-sharded-worker",
            "--model-root",
            str(model_root),
            "--device",
            device,
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise LocalModelUnavailable("could not start the sharded HWE Qwen worker") from exc
        try:
            assert self._process.stdout is not None
            ready_line = self._process.stdout.readline()
            ready = json.loads(ready_line) if ready_line else None
            if not isinstance(ready, dict) or ready.get("ready") is not True:
                raise LocalModelUnavailable("sharded HWE Qwen worker did not become ready")
        except (json.JSONDecodeError, OSError, LocalModelUnavailable):
            self.close()
            raise

    def predict_action(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float,
        seed: int,
    ) -> str:
        return self.predict_actions([messages], temperatures=[temperature], seeds=[seed])[0]

    def predict_actions(
        self,
        messages: Sequence[Sequence[Mapping[str, Any]]],
        *,
        temperatures: Sequence[float],
        seeds: Sequence[int],
    ) -> list[str]:
        if not len(messages) == len(temperatures) == len(seeds):
            raise ValueError("subprocess Qwen request lengths differ")
        if self._process.stdin is None or self._process.stdout is None:
            raise LocalModelUnavailable("sharded HWE Qwen worker pipes are unavailable")
        request = {
            "messages": [[dict(message) for message in context] for context in messages],
            "temperatures": list(temperatures),
            "seeds": list(seeds),
        }
        try:
            self._process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
            response_line = self._process.stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            raise LocalModelUnavailable("sharded HWE Qwen worker stopped during inference") from exc
        if not response_line:
            raise LocalModelUnavailable("sharded HWE Qwen worker exited during inference")
        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise LocalModelUnavailable("sharded HWE Qwen worker returned malformed JSON") from exc
        if not isinstance(response, dict) or response.get("ok") is not True:
            detail = response.get("error") if isinstance(response, dict) else None
            raise LocalModelUnavailable(f"sharded HWE Qwen worker failed: {detail}")
        outputs = response.get("outputs")
        if (
            not isinstance(outputs, list)
            or len(outputs) != len(messages)
            or any(not isinstance(output, str) for output in outputs)
        ):
            raise LocalModelUnavailable("sharded HWE Qwen worker returned invalid outputs")
        return outputs

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout is not None:
            process.stdout.close()


class SubprocessParallelLocalQwenActionPredictor:
    """Run parallel Qwen replicas in an isolated process group.

    The long-context fallback cannot safely share a Python process that previously owned CUDA
    replica workers on the HWE host.  Keeping the replica pool behind a process-group boundary
    lets the router terminate every replica (including ProcessPool children) before it starts the
    next CUDA layout.  Each device entry may be a single card or a ``+``-joined model-parallel
    group.  The JSON protocol is the same as the sharded adapter.
    """

    def __init__(self, model_root: Path, *, devices: Sequence[str]) -> None:
        if not devices or len(set(devices)) != len(devices):
            raise LocalModelUnavailable("isolated Qwen replicas require distinct devices")
        command = [
            sys.executable,
            "-m",
            "verigym.hwe.local_models",
            "--hwe-replica-worker",
            "--model-root",
            str(model_root),
            "--devices",
            ",".join(devices),
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            raise LocalModelUnavailable("could not start the isolated Qwen replica worker") from exc
        try:
            assert self._process.stdout is not None
            ready_line = self._process.stdout.readline()
            ready = json.loads(ready_line) if ready_line else None
            if not isinstance(ready, dict) or ready.get("ready") is not True:
                raise LocalModelUnavailable("isolated Qwen replica worker did not become ready")
        except (json.JSONDecodeError, OSError, LocalModelUnavailable):
            self.close()
            raise

    def predict_action(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float,
        seed: int,
    ) -> str:
        return self.predict_actions([messages], temperatures=[temperature], seeds=[seed])[0]

    def predict_actions(
        self,
        messages: Sequence[Sequence[Mapping[str, Any]]],
        *,
        temperatures: Sequence[float],
        seeds: Sequence[int],
    ) -> list[str]:
        if not len(messages) == len(temperatures) == len(seeds):
            raise ValueError("isolated Qwen replica request lengths differ")
        if self._process.stdin is None or self._process.stdout is None:
            raise LocalModelUnavailable("isolated Qwen replica worker pipes are unavailable")
        request = {
            "messages": [[dict(message) for message in context] for context in messages],
            "temperatures": list(temperatures),
            "seeds": list(seeds),
        }
        try:
            self._process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
            response_line = self._process.stdout.readline()
        except (BrokenPipeError, OSError) as exc:
            raise LocalModelUnavailable(
                "isolated Qwen replica worker stopped during inference"
            ) from exc
        if not response_line:
            raise LocalModelUnavailable("isolated Qwen replica worker exited during inference")
        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise LocalModelUnavailable(
                "isolated Qwen replica worker returned malformed JSON"
            ) from exc
        if not isinstance(response, dict) or response.get("ok") is not True:
            detail = response.get("error") if isinstance(response, dict) else None
            raise LocalModelUnavailable(f"isolated Qwen replica worker failed: {detail}")
        outputs = response.get("outputs")
        if (
            not isinstance(outputs, list)
            or len(outputs) != len(messages)
            or any(not isinstance(output, str) for output in outputs)
        ):
            raise LocalModelUnavailable("isolated Qwen replica worker returned invalid outputs")
        return outputs

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        # The worker owns a ProcessPoolExecutor whose children own the CUDA contexts.  Terminate
        # the complete session rather than waiting on a potentially blocked executor shutdown.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, AttributeError):
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, AttributeError):
                try:
                    process.kill()
                except OSError:
                    pass
            process.wait()
        if process.stdout is not None:
            process.stdout.close()


class AdaptiveLocalQwenActionPredictor:
    """Use parallel single-card replicas until a reference needs the sharded long-context path.

    Qwen3.5's text-only weights fit on one A30, but the fallback gated-delta kernel does not
    accept every 24-GiB-card sequence length.  The HWE NAP workload is therefore split by the
    exact chat-template input length: short requests use one replica per card, while long
    requests use one model balanced across the complete card group.  Only one mode is resident at
    a time, so the switch cannot silently oversubscribe GPU memory.  Once a long-context model is
    selected it remains resident for a candidate-only batch whose anchor predictions are already
    cached.  A new multi-context NAP batch may safely return to replicas because the old worker is
    terminated as a complete process group before another CUDA context is created.
    """

    _REPLICA_REENTRY_TOKENS = 20_000
    _REPLICA_EXIT_TOKENS = 24_000

    def __init__(self, model_root: Path, *, replica_devices: Sequence[str]) -> None:
        if len(replica_devices) < 2:
            raise LocalModelUnavailable("adaptive Qwen NAP requires at least two replicas")
        if any("+" in device for device in replica_devices):
            raise LocalModelUnavailable("adaptive Qwen replicas must be single CUDA devices")
        self._model_root = model_root
        self._replica_devices = tuple(replica_devices)
        self._sharded_device = "+".join(replica_devices)
        self._long_context_devices = _long_context_device_groups(self._replica_devices)
        _, transformers = _imports()
        root = _safe_model_root(model_root)
        self._tokenizer = transformers.AutoTokenizer.from_pretrained(
            str(root), local_files_only=True, trust_remote_code=False
        )
        self._length_cache: dict[str, int] = {}
        self._active: (
            SubprocessParallelLocalQwenActionPredictor | SubprocessLocalQwenActionPredictor | None
        ) = None
        self._mode: str | None = None
        self._switches: list[dict[str, Any]] = []

    def predict_action(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float,
        seed: int,
    ) -> str:
        return self.predict_actions([messages], temperatures=[temperature], seeds=[seed])[0]

    def predict_actions(
        self,
        messages: Sequence[Sequence[Mapping[str, Any]]],
        *,
        temperatures: Sequence[float],
        seeds: Sequence[int],
    ) -> list[str]:
        if not len(messages) == len(temperatures) == len(seeds):
            raise ValueError("adaptive Qwen NAP request lengths differ")
        if not messages:
            return []
        input_tokens = max(self._input_length(context) for context in messages)
        desired = self._desired_mode(input_tokens, request_count=len(messages))
        self._ensure_mode(desired, input_tokens=input_tokens, reason="length_policy")
        assert self._active is not None
        try:
            return self._active.predict_actions(messages, temperatures=temperatures, seeds=seeds)
        except Exception as exc:
            if self._mode != "replicas" or not _is_cuda_runtime_failure(exc):
                raise
            # A driver/kernel boundary can be lower than the conservative policy on a particular
            # host.  Retry the exact request on the already validated seven-card sharded path.
            self._ensure_mode("sharded", input_tokens=input_tokens, reason=type(exc).__name__)
            assert self._active is not None
            return self._active.predict_actions(messages, temperatures=temperatures, seeds=seeds)

    def close(self) -> None:
        if self._active is not None:
            self._active.close()
            self._active = None
            self._mode = None

    def runtime_summary(self) -> dict[str, Any]:
        return {
            "mode": self._mode,
            "replica_devices": list(self._replica_devices),
            "sharded_device": self._sharded_device,
            "long_context_devices": list(self._long_context_devices),
            "replica_reentry_tokens": self._REPLICA_REENTRY_TOKENS,
            "replica_exit_tokens": self._REPLICA_EXIT_TOKENS,
            "switches": [dict(item) for item in self._switches],
        }

    def _input_length(self, messages: Sequence[Mapping[str, Any]]) -> int:
        key = content_hash(list(messages))
        cached = self._length_cache.get(key)
        if cached is not None:
            return cached
        prompt_messages = _qwen_messages(messages)
        prompt_messages.append(
            {
                "role": "user",
                "content": (
                    "Return only one JSON object with fields action and arguments for the next "
                    "HWE native-shell tool call. Do not explain your choice."
                ),
            }
        )
        encoded = self._tokenizer.apply_chat_template(
            prompt_messages,
            tokenize=True,
            add_generation_prompt=True,
            tools=hwe_tool_definitions(profile_id="hwe_standard_v2"),
            enable_thinking=False,
        )
        input_ids = encoded["input_ids"]
        length = int(input_ids.shape[-1]) if hasattr(input_ids, "shape") else len(input_ids)
        self._length_cache[key] = length
        return length

    def _desired_mode(self, input_tokens: int, *, request_count: int) -> str:
        if self._mode == "replicas":
            return "sharded" if input_tokens > self._REPLICA_EXIT_TOKENS else "replicas"
        if self._mode == "sharded":
            # AnchorNapValidator passes one candidate after the eight long-reference anchors are
            # cached.  Keep the sharded worker for that request; a new multi-context validation
            # can return to replicas through the isolated process-group boundary.
            return (
                "replicas"
                if request_count > 1 and input_tokens <= self._REPLICA_REENTRY_TOKENS
                else "sharded"
            )
        return "replicas" if input_tokens <= self._REPLICA_REENTRY_TOKENS else "sharded"

    def _ensure_mode(self, mode: str, *, input_tokens: int, reason: str) -> None:
        if mode == self._mode and self._active is not None:
            return
        previous = self._mode
        if self._active is not None:
            self._active.close()
        if mode == "replicas":
            self._active = SubprocessParallelLocalQwenActionPredictor(
                self._model_root, devices=self._replica_devices
            )
        else:
            self._active = SubprocessParallelLocalQwenActionPredictor(
                self._model_root, devices=self._long_context_devices
            )
        self._mode = mode
        self._switches.append(
            {
                "from": previous,
                "to": mode,
                "input_tokens": input_tokens,
                "reason": reason,
            }
        )


class LocalCoactGenerator:
    """Generate one candidate from the official local CoACT checkpoint."""

    def __init__(self, checkpoint_root: Path, *, device: str = "cuda:0") -> None:
        runtime_device, shard_count = _prepare_device_group(device)
        torch, transformers = _imports()
        self._torch = torch
        self._device = runtime_device
        root = _safe_model_root(checkpoint_root)
        self._tokenizer = transformers.AutoTokenizer.from_pretrained(
            str(root), local_files_only=True, trust_remote_code=False
        )
        model_kwargs: dict[str, Any] = {
            "local_files_only": True,
            "trust_remote_code": False,
            "dtype": torch.bfloat16,
        }
        if shard_count == 1:
            model_kwargs["device_map"] = {"": runtime_device}
        else:
            model_kwargs["device_map"] = "balanced"
            model_kwargs["max_memory"] = {index: "22GiB" for index in range(shard_count)}
        self._model = transformers.AutoModelForCausalLM.from_pretrained(str(root), **model_kwargs)
        self._model.eval()

    def generate(self, prompt: str, *, seed: int, max_new_tokens: int) -> str:
        torch = self._torch
        inputs = self._tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
            enable_thinking=False,
        )
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with _seed_context(torch, self._device, seed):
            with torch.inference_mode():
                output = self._model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=True,
                    temperature=0.7,
                    top_p=0.95,
                    logits_to_keep=1,
                )
        prompt_length = int(inputs["input_ids"].shape[-1])
        return cast(
            str,
            self._tokenizer.decode(output[0][prompt_length:], skip_special_tokens=True),
        ).strip()


def _imports() -> tuple[Any, Any]:
    try:
        import torch  # type: ignore[import-not-found]
        import transformers
    except ImportError as exc:  # pragma: no cover - depends on optional environment
        raise LocalModelUnavailable(
            "local HWE NAP/CoACT inference requires torch and transformers"
        ) from exc
    return torch, transformers


_WORKER_PREDICTOR: LocalQwenActionPredictor | None = None


def _initialize_qwen_worker(model_root: str, device: str) -> None:
    global _WORKER_PREDICTOR
    _WORKER_PREDICTOR = LocalQwenActionPredictor(Path(model_root), device=device)


def _predict_qwen_worker(
    request: tuple[list[dict[str, Any]], float, int],
) -> str:
    if _WORKER_PREDICTOR is None:
        raise LocalModelUnavailable("Qwen worker was not initialized")
    messages, temperature, seed = request
    return _WORKER_PREDICTOR.predict_action(
        messages,
        temperature=temperature,
        seed=seed,
    )


def _run_sharded_worker(model_root: Path, device: str) -> None:
    predictor = LocalQwenActionPredictor(model_root, device=device)
    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request is not an object")
            messages = request.get("messages")
            temperatures = request.get("temperatures")
            seeds = request.get("seeds")
            if not isinstance(messages, list) or not isinstance(temperatures, list):
                raise ValueError("request fields are malformed")
            if not isinstance(seeds, list):
                raise ValueError("request seeds are malformed")
            outputs = [
                predictor.predict_action(
                    context,
                    temperature=float(temperature),
                    seed=int(seed),
                )
                for context, temperature, seed in zip(messages, temperatures, seeds, strict=True)
            ]
            response: dict[str, Any] = {"ok": True, "outputs": outputs}
        except BaseException as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _run_replica_worker(model_root: Path, devices: Sequence[str]) -> None:
    predictor = ParallelLocalQwenActionPredictor(model_root, devices=devices)
    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request is not an object")
                messages = request.get("messages")
                temperatures = request.get("temperatures")
                seeds = request.get("seeds")
                if not isinstance(messages, list) or not isinstance(temperatures, list):
                    raise ValueError("request fields are malformed")
                if not isinstance(seeds, list):
                    raise ValueError("request seeds are malformed")
                outputs = predictor.predict_actions(
                    messages,
                    temperatures=[float(value) for value in temperatures],
                    seeds=[int(value) for value in seeds],
                )
                response: dict[str, Any] = {"ok": True, "outputs": outputs}
            except BaseException as exc:
                response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    finally:
        predictor.close()


def _module_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hwe-sharded-worker", action="store_true")
    parser.add_argument("--hwe-replica-worker", action="store_true")
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--device")
    parser.add_argument("--devices")
    arguments = parser.parse_args()
    if arguments.model_root is None:
        parser.error("a local --model-root is required")
    if arguments.hwe_sharded_worker and not arguments.hwe_replica_worker:
        if arguments.device is None:
            parser.error("--hwe-sharded-worker requires --device")
        _run_sharded_worker(arguments.model_root, arguments.device)
        return
    if arguments.hwe_replica_worker and not arguments.hwe_sharded_worker:
        if not arguments.devices:
            parser.error("--hwe-replica-worker requires --devices")
        devices = tuple(item.strip() for item in arguments.devices.split(",") if item.strip())
        _run_replica_worker(arguments.model_root, devices)
        return
    parser.error("choose exactly one HWE worker mode")


@contextmanager
def _seed_context(torch: Any, device: str, seed: int) -> Iterator[None]:
    """Seed the active CUDA generator without sharing a global generator argument."""

    if device.startswith("cuda") and torch.cuda.is_available():
        with torch.cuda.device(device):
            torch.cuda.manual_seed(seed)
            yield
    else:
        torch.manual_seed(seed)
        yield


def _qwen_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Adapt persisted OpenAI-style calls to Qwen's mapping-valued template arguments."""

    result: list[dict[str, Any]] = []
    for message in messages:
        current = dict(message)
        calls = current.get("tool_calls")
        if isinstance(calls, list):
            normalized_calls: list[dict[str, Any]] = []
            for call in calls:
                if not isinstance(call, Mapping):
                    continue
                normalized = dict(call)
                function = normalized.get("function")
                if isinstance(function, Mapping):
                    normalized_function = dict(function)
                    arguments = normalized_function.get("arguments")
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            pass
                    normalized_function["arguments"] = arguments
                    normalized["function"] = normalized_function
                normalized_calls.append(normalized)
            current["tool_calls"] = normalized_calls
        result.append(current)
    return result


def _safe_model_root(path: Path) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise LocalModelUnavailable("local model root must be a non-symlink directory")
    config = path / "config.json"
    if config.is_symlink() or not config.is_file():
        raise LocalModelUnavailable("local model root lacks config.json")
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalModelUnavailable("local model config is invalid") from exc
    if payload.get("auto_map") or payload.get("trust_remote_code") is True:
        raise LocalModelUnavailable("remote model code is forbidden")
    return path.resolve(strict=True)


def _parse_device_group(value: str) -> tuple[str, ...]:
    parts = tuple(item.strip() for item in value.split("+") if item.strip())
    if not parts or any(not item.startswith("cuda:") for item in parts):
        raise LocalModelUnavailable(f"invalid CUDA device group: {value}")
    for item in parts:
        try:
            index = int(item.removeprefix("cuda:"))
        except ValueError as exc:
            raise LocalModelUnavailable(f"invalid CUDA device group: {value}") from exc
        if index < 0:
            raise LocalModelUnavailable(f"invalid CUDA device group: {value}")
    return parts


def _long_context_device_groups(devices: Sequence[str]) -> tuple[str, ...]:
    """Partition exclusive cards into a few independent model-parallel long-context replicas."""

    if not devices:
        raise LocalModelUnavailable("long-context Qwen replicas require at least one device")
    if len(devices) < 4:
        return ("+".join(devices),)
    # Three groups are useful for the full seven-card allocation (2/2/3), but a six-card
    # allocation should use two 3-card models.  The 2/2/2 layout leaves each long-context model
    # with too little headroom on the HWE host and has produced a driver-level invalid-argument
    # failure after repeated long-context mode switches.
    group_count = 3 if len(devices) >= 7 else 2
    base, remainder = divmod(len(devices), group_count)
    sizes = [base] * group_count
    # Put any extra card in the final group.  For the seven-card HWE allocation this is 2/2/3,
    # which matches the validated long-context probe while keeping all groups independent.
    sizes[-1] += remainder
    groups: list[str] = []
    offset = 0
    for size in sizes:
        groups.append("+".join(devices[offset : offset + size]))
        offset += size
    return tuple(groups)


def _prepare_device_group(value: str) -> tuple[str, int]:
    parts = _parse_device_group(value)
    if len(parts) == 1:
        return parts[0], 1
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    visible_ids = tuple(item.strip() for item in visible.split(",")) if visible else ()
    physical_ids: list[str] = []
    for part in parts:
        logical_index = int(part.removeprefix("cuda:"))
        if visible_ids:
            if logical_index >= len(visible_ids):
                raise LocalModelUnavailable(
                    f"device {part} is outside CUDA_VISIBLE_DEVICES={visible}"
                )
            physical_ids.append(visible_ids[logical_index])
        else:
            physical_ids.append(str(logical_index))
    os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(physical_ids)
    return "cuda:0", len(parts)


def _is_cuda_runtime_failure(error: BaseException) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in ("cuda", "out of memory", "cublas", "driver error", "invalid argument")
    )


__all__ = [
    "LocalCoactGenerator",
    "LocalModelUnavailable",
    "LocalQwenActionPredictor",
    "AdaptiveLocalQwenActionPredictor",
    "ParallelLocalQwenActionPredictor",
    "SubprocessLocalQwenActionPredictor",
    "SubprocessParallelLocalQwenActionPredictor",
]


if __name__ == "__main__":
    _module_main()
