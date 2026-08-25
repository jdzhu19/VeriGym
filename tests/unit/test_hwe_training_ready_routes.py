from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from verigym.hwe import local_models
from verigym.hwe.coact import (
    COACT_CANDIDATE_SEEDS,
    compress_hwe_trajectory,
    parse_coact_response,
    render_coact_prompt,
)
from verigym.hwe.local_models import AdaptiveLocalQwenActionPredictor
from verigym.hwe.nap import (
    AnchorNapValidator,
    canonical_action_hash,
    parse_hwe_action,
    typed_action_similarity,
)


@dataclass(frozen=True)
class _CharCounter:
    tokenizer_id: str = "test"
    tokenizer_hash: str = "0" * 64

    def count(self, text: str) -> int:
        return len(text)


class _StablePredictor:
    def __init__(self) -> None:
        self.calls: list[tuple[float, int, int]] = []

    def predict_action(
        self, messages: list[dict[str, Any]], *, temperature: float, seed: int
    ) -> dict[str, Any]:
        self.calls.append((temperature, seed, len(messages)))
        return {"name": "shell", "arguments": {"command": "true"}}


class _AlwaysPassNap:
    def __init__(self) -> None:
        self.contexts: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []

    def validate(self, uncompressed: list[dict[str, Any]], compressed: list[dict[str, Any]]) -> Any:
        self.contexts.append((uncompressed, compressed))
        return type(
            "Result",
            (),
            {"passed": True, "top_k_score": 1.0, "as_dict": lambda self: {"passed": True}},
        )()


class _CodeCompressor:
    def generate(self, prompt: str, *, seed: int, max_new_tokens: int) -> str:
        assert "Public task goal" in prompt
        assert "private reasoning" not in prompt.lower()
        return json.dumps({"type": "code", "content": ["2-500:repeated listing"]})


def _messages() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "repair the issue"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c0",
                    "type": "function",
                    "function": {
                        "name": "shell",
                        "arguments": '{"command":"true"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": "line 1\n" + "\n".join(f"line {index}" for index in range(2, 601)),
            "tool_call_id": "c0",
            "name": "shell",
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "inspect_diff",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": "short result",
            "tool_call_id": "c1",
            "name": "inspect_diff",
        },
        {"role": "assistant", "content": "finished"},
    ]


def test_typed_hwe_action_similarity_is_tool_aware() -> None:
    left = {"name": "shell", "arguments": {"command": "printf   ok"}}
    right = {"name": "shell", "arguments": {"command": "printf ok"}}
    assert parse_hwe_action(left) is not None
    assert typed_action_similarity(left, right) == pytest.approx(1.0)
    assert (
        typed_action_similarity(
            {
                "name": "shell",
                "arguments": {"command": "sed -n '610,680p' repository/core/decoder.sv"},
            },
            {
                "name": "shell",
                "arguments": {"command": "sed -n '610,690p' repository/core/decoder.sv"},
            },
        )
        > 0.6
    )
    search_candidate = {
        "name": "shell",
        "arguments": {
            "command": (
                'grep -n "zext.h\\|packw\\|pack" '
                "repository/docs/01_cva6_user/RISCV_Instructions_RVZbb.rst "
                "| sed -n '1,100p'"
            )
        },
    }
    assert (
        typed_action_similarity(
            search_candidate,
            {
                "name": "shell",
                "arguments": {
                    "command": (
                        'grep -n "zext\\|pack" '
                        "repository/docs/01_cva6_user/RISCV_Instructions_RVZbb.rst "
                        "| sed -n '1,50p'"
                    )
                },
            },
        )
        > 0.6
    )
    assert (
        typed_action_similarity(
            search_candidate,
            {
                "name": "shell",
                "arguments": {
                    "command": (
                        'rg -n -E "zext.h\\|packw\\|pack.*rd.*rs" '
                        "repository/docs/01_cva6_user/RISCV_Instructions_RVZbb.rst "
                        "repository/docs/01_cva6_user/RISCV_Instructions_RV32ZCb.rst"
                    )
                },
            },
        )
        > 0.6
    )
    assert typed_action_similarity(
        search_candidate,
        {
            "name": "shell",
            "arguments": {
                "command": (
                    'grep -n "unrelated" repository/docs/01_cva6_user/RISCV_Instructions_RVZbb.rst'
                )
            },
        },
    ) == pytest.approx(0.2)
    assert typed_action_similarity(
        {"name": "shell", "arguments": {"command": "sed -n '610,680p' a.sv"}},
        {"name": "shell", "arguments": {"command": "sed -n '610,690p' b.sv"}},
    ) == pytest.approx(0.2)
    assert typed_action_similarity(left, {"name": "read_file", "arguments": {"path": "a"}}) == 0.0
    assert canonical_action_hash(
        {"name": "inspect_diff", "arguments": "{}"}
    ) == canonical_action_hash({"name": "inspect_diff", "arguments": {}})
    assert (
        parse_hwe_action(
            "<tool_call><function=shell><parameter=command>\ntrue\n</parameter>"
            "</function></tool_call>"
        )
        is not None
    )
    assert parse_hwe_action(
        "<tool_call>\n<function=shell>\n<parameter=command>\nfind . -name decoder.sv -print\n"
        "</parameter>\n</function>"
    ) == parse_hwe_action(
        {"name": "shell", "arguments": {"command": "find . -name decoder.sv -print"}}
    )
    assert (
        parse_hwe_action(
            "<tool_call>\n<function=read_file>\n<parameter=path>\nrepository/core/decoder.sv\n"
            "</parameter>"
        )
        is not None
    )
    assert (
        parse_hwe_action(
            "<tool_call>\n<function=shell>\n<parameter=command>\n"
            "cat repository/core/decoder.sv | sed -n '750,85"
        )
        is None
    )
    assert (
        parse_hwe_action('reasoning {"action":"shell","arguments":{"command":"true"}}') is not None
    )


def test_anchor_nap_uses_eight_anchors_and_top_three_mean() -> None:
    predictor = _StablePredictor()
    result = AnchorNapValidator(predictor).validate(
        [{"role": "user", "content": "goal"}],
        [{"role": "user", "content": "goal"}, {"role": "tool", "content": "compact"}],
    )
    assert result.passed is True
    assert result.anchor_count == 8
    assert result.predictor_calls == 9
    assert [temperature for temperature, _, _ in predictor.calls[:8]] == [0.7] * 8
    assert predictor.calls[-1][0] == 0.0


def test_anchor_nap_reuses_identical_uncompressed_anchor_predictions() -> None:
    predictor = _StablePredictor()
    validator = AnchorNapValidator(predictor)
    uncompressed = [{"role": "user", "content": "goal"}]
    first_candidate = [*uncompressed, {"role": "tool", "content": "first"}]
    second_candidate = [*uncompressed, {"role": "tool", "content": "second"}]

    assert validator.validate(uncompressed, first_candidate).passed is True
    assert validator.validate(uncompressed, second_candidate).passed is True
    assert len(predictor.calls) == 10


def test_anchor_nap_accepts_exact_identity_without_stochastic_false_negative() -> None:
    class _TemperatureSensitivePredictor(_StablePredictor):
        def predict_action(
            self, messages: list[dict[str, Any]], *, temperature: float, seed: int
        ) -> dict[str, Any]:
            self.calls.append((temperature, seed, len(messages)))
            command = "true" if temperature == 0.0 else "false"
            return {"name": "shell", "arguments": {"command": command}}

    predictor = _TemperatureSensitivePredictor()
    messages = [{"role": "user", "content": "goal"}]
    result = AnchorNapValidator(predictor).validate(messages, list(messages))

    assert result.passed is True
    assert result.validation_mode == "identity_exact"
    assert result.predictor_calls == 0
    assert result.candidate_action is None
    assert result.top_k_score == pytest.approx(1.0)
    assert predictor.calls == []


def test_adaptive_nap_switches_between_replica_and_sharded_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeParallel:
        instances: list[_FakeParallel] = []

        def __init__(
            self,
            model_root: Any,
            *,
            devices: tuple[str, ...] | None = None,
            device: str | None = None,
        ) -> None:
            self.devices = devices if devices is not None else (device,)
            self.closed = False
            self.instances.append(self)

        def predict_actions(self, messages: Any, *, temperatures: Any, seeds: Any) -> list[str]:
            return ["ok"] * len(messages)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(local_models, "ParallelLocalQwenActionPredictor", _FakeParallel)
    monkeypatch.setattr(local_models, "SubprocessParallelLocalQwenActionPredictor", _FakeParallel)
    monkeypatch.setattr(local_models, "SubprocessLocalQwenActionPredictor", _FakeParallel)
    predictor = object.__new__(AdaptiveLocalQwenActionPredictor)
    predictor._model_root = object()
    predictor._replica_devices = tuple(f"cuda:{index}" for index in range(7))
    predictor._sharded_device = "+".join(predictor._replica_devices)
    predictor._long_context_devices = (
        "cuda:0+cuda:1",
        "cuda:2+cuda:3",
        "cuda:4+cuda:5+cuda:6",
    )
    predictor._tokenizer = object()
    predictor._length_cache = {}
    predictor._active = None
    predictor._mode = None
    predictor._switches = []
    monkeypatch.setattr(
        predictor,
        "_input_length",
        lambda messages: 10_000 if messages[0].get("content") == "short" else 80_000,
    )

    assert predictor.predict_actions(
        [[{"role": "user", "content": "short"}]], temperatures=[0.0], seeds=[0]
    ) == ["ok"]
    assert _FakeParallel.instances[-1].devices == predictor._replica_devices
    assert predictor.predict_actions(
        [[{"role": "user", "content": "long"}]], temperatures=[0.0], seeds=[0]
    ) == ["ok"]
    assert _FakeParallel.instances[-1].devices == predictor._long_context_devices
    assert _FakeParallel.instances[-2].closed is True
    assert predictor.predict_actions(
        [[{"role": "user", "content": "short"}]], temperatures=[0.0], seeds=[0]
    ) == ["ok"]
    assert _FakeParallel.instances[-1].devices == predictor._long_context_devices
    # A single candidate can be the cache-missing tail of a long NAP validation, so it remains
    # sharded.  A fresh multi-context validation is a new record and can safely re-enter replicas.
    assert predictor.predict_actions(
        [
            [{"role": "user", "content": "short"}],
            [{"role": "user", "content": "short"}],
        ],
        temperatures=[0.0, 0.0],
        seeds=[0, 1],
    ) == ["ok", "ok"]
    assert _FakeParallel.instances[-1].devices == predictor._replica_devices
    assert len(_FakeParallel.instances) == 3
    assert predictor.runtime_summary()["switches"] == [
        {"from": None, "to": "replicas", "input_tokens": 10_000, "reason": "length_policy"},
        {"from": "replicas", "to": "sharded", "input_tokens": 80_000, "reason": "length_policy"},
        {"from": "sharded", "to": "replicas", "input_tokens": 10_000, "reason": "length_policy"},
    ]


def test_adaptive_nap_retries_replica_cuda_failure_on_sharded_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeParallel:
        def __init__(
            self,
            model_root: Any,
            *,
            devices: tuple[str, ...] | None = None,
            device: str | None = None,
        ) -> None:
            self.devices = devices if devices is not None else (device,)
            self.closed = False

        def predict_actions(self, messages: Any, *, temperatures: Any, seeds: Any) -> list[str]:
            if all("+" not in device for device in self.devices):
                raise RuntimeError("CUDA driver error: invalid argument")
            return ["recovered"] * len(messages)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(local_models, "ParallelLocalQwenActionPredictor", _FakeParallel)
    monkeypatch.setattr(local_models, "SubprocessParallelLocalQwenActionPredictor", _FakeParallel)
    monkeypatch.setattr(local_models, "SubprocessLocalQwenActionPredictor", _FakeParallel)
    predictor = object.__new__(AdaptiveLocalQwenActionPredictor)
    predictor._model_root = object()
    predictor._replica_devices = ("cuda:0", "cuda:1")
    predictor._sharded_device = "cuda:0+cuda:1"
    predictor._long_context_devices = ("cuda:0+cuda:1",)
    predictor._tokenizer = object()
    predictor._length_cache = {}
    predictor._active = None
    predictor._mode = None
    predictor._switches = []
    monkeypatch.setattr(predictor, "_input_length", lambda messages: 10_000)

    assert predictor.predict_actions(
        [[{"role": "user", "content": "short"}]], temperatures=[0.0], seeds=[0]
    ) == ["recovered"]
    assert predictor._mode == "sharded"
    assert predictor.runtime_summary()["switches"][-1]["reason"] == "RuntimeError"


def test_long_context_groups_keep_six_card_models_wide() -> None:
    assert local_models._long_context_device_groups(
        ("cuda:0", "cuda:1", "cuda:2", "cuda:3", "cuda:4", "cuda:5")
    ) == ("cuda:0+cuda:1+cuda:2", "cuda:3+cuda:4+cuda:5")
    assert local_models._long_context_device_groups(
        ("cuda:0", "cuda:1", "cuda:2", "cuda:3", "cuda:4", "cuda:5", "cuda:6")
    ) == ("cuda:0+cuda:1", "cuda:2+cuda:3", "cuda:4+cuda:5+cuda:6")


def test_parallel_nap_uses_direct_predictor_for_one_sharded_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeDirect:
        instances: list[_FakeDirect] = []

        def __init__(self, model_root: Any, *, device: str) -> None:
            self.model_root = model_root
            self.device = device
            self.closed = False
            self.instances.append(self)

        def predict_action(self, messages: Any, *, temperature: float, seed: int) -> str:
            return f"{len(messages)}:{temperature}:{seed}"

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(local_models, "LocalQwenActionPredictor", _FakeDirect)
    predictor = local_models.ParallelLocalQwenActionPredictor(object(), devices=("cuda:0+cuda:1",))
    assert len(_FakeDirect.instances) == 1
    assert _FakeDirect.instances[0].device == "cuda:0+cuda:1"
    assert predictor.predict_actions(
        [[{"role": "user", "content": "one"}], [{"role": "user", "content": "two"}]],
        temperatures=[0.0, 0.7],
        seeds=[0, 1],
    ) == ["1:0.0:0", "1:0.7:1"]
    predictor.close()
    assert _FakeDirect.instances[0].closed is True


def test_subprocess_sharded_predictor_uses_framed_json_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeStream:
        def __init__(self, lines: list[str] | None = None) -> None:
            self.lines = iter(lines or [])
            self.writes: list[str] = []
            self.closed = False

        def readline(self) -> str:
            return next(self.lines, "")

        def write(self, value: str) -> None:
            self.writes.append(value)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    class _FakeProcess:
        def __init__(self) -> None:
            self.stdin = _FakeStream()
            self.stdout = _FakeStream(
                [
                    '{"ready": true}\n',
                    '{"ok": true, "outputs": ["<tool_call>"]}\n',
                ]
            )
            self.terminated = False

        def wait(self, *, timeout: float | None = None) -> int:
            del timeout
            return 0

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.terminated = True

    process = _FakeProcess()
    monkeypatch.setattr(local_models.subprocess, "Popen", lambda *args, **kwargs: process)
    predictor = local_models.SubprocessLocalQwenActionPredictor(object(), device="cuda:0+cuda:1")
    assert predictor.predict_actions(
        [[{"role": "user", "content": "goal"}]], temperatures=[0.0], seeds=[0]
    ) == ["<tool_call>"]
    request = json.loads(process.stdin.writes[0])
    assert request["temperatures"] == [0.0]
    assert request["seeds"] == [0]
    predictor.close()
    assert process.stdin.closed is True


def test_coact_parser_reconstructs_one_based_omission_ranges() -> None:
    original = "one\ntwo\nthree\nfour"
    parsed = parse_coact_response(
        '{"type":"code","content":["2-3:unneeded middle"]}', original_text=original
    )
    assert parsed is not None
    assert parsed.effective_text == "one\n(compressed 2 lines: unneeded middle)\nfour"
    assert parse_coact_response('{"type":"plain","content":""}', original_text=original) is None


def test_coact_replaces_observations_once_and_preserves_call_identity() -> None:
    nap = _AlwaysPassNap()
    compressed, manifest = compress_hwe_trajectory(
        {
            "sft_messages": _messages(),
            "compaction_manifest": {
                "step_outcomes": [
                    {"sequence": 0, "action": "shell"},
                    {"sequence": 1, "action": "inspect_diff"},
                ]
            },
        },
        task_goal="repair the issue",
        counter=_CharCounter(),
        generator=_CodeCompressor(),
        nap_validator=nap,  # type: ignore[arg-type]
    )
    assert len(COACT_CANDIDATE_SEEDS) == 8
    assert compressed[3]["content"].startswith("line 1")
    assert compressed[2]["tool_calls"] == _messages()[2]["tool_calls"]
    assert compressed[4]["tool_calls"] == _messages()[4]["tool_calls"]
    assert manifest["causal_validation"] == "passed"
    assert nap.contexts[1][0][3]["content"].startswith("line 1")


def test_coact_prompt_has_only_declared_public_fields() -> None:
    prompt = render_coact_prompt(
        task_goal="public goal",
        tool_call={"name": "shell", "arguments": {"command": "true"}},
        observation_type="diagnostic_or_command_output",
        observation="exit_code=0",
    )
    assert "public goal" in prompt
    assert "exit_code=0" in prompt
    assert "hidden tests" not in prompt.lower()
    assert "reference patch" not in prompt.lower()
