"""CoACT-style, observation-entry compression for complete HWE trajectories.

This module intentionally keeps model serving behind two small protocols.  The persisted artifact
contains only the public task goal, typed tool calls, compact observations and deterministic
compression metadata; provider events and raw observations never enter the SFT record.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from verigym.core.hashing import content_hash, hash_bytes
from verigym.hwe.nap import AnchorNapValidator
from verigym.hwe.observation import TokenCounter

COACT_FORMAT_ID = "hwe_coact_observation_entry_compression_v1"
COACT_DATASET_FORMAT_ID = "verigym_hwe_coact_multiturn_sft_dataset_v1"
COACT_EXAMPLE_FORMAT_ID = "verigym_hwe_coact_multiturn_sft_v1"
COACT_CHECKPOINT_MODEL_ID = "Kndy666/CoACT"
COACT_CHECKPOINT_REVISION = "1b2d660dfa5fccf80a5e3c508a9f0d3c1930ccf5"
COACT_WEIGHT_SIZE_BYTES = 8_410_314_240
COACT_MAX_LENGTH = 65_536
COACT_BYPASS_TOKENS = 512
COACT_MAX_CANDIDATES = 8
COACT_CANDIDATE_SEEDS = tuple(range(COACT_MAX_CANDIDATES))

_RANGE = re.compile(r"^(?P<start>[1-9]\d*)(?:-(?P<end>[1-9]\d*))?(?::(?P<summary>.*))?$")
_DIAGNOSTIC = re.compile(
    r"(?:\berror\b|\bfatal\b|\bassert(?:ion)?\b|\btraceback\b|\bexception\b|"
    r"\bfailed\b|\bexpected\b|\bactual\b|\bseed\b)",
    re.IGNORECASE,
)
_HEADER_FIELD = re.compile(r"\b(?:exit_code|seed|expected|actual|changed_paths)\b")
_SAFE_CHECKPOINT_FILES = frozenset(
    {
        ".gitattributes",
        "README.md",
        "LICENSE",
        "chat_template.jinja",
        "config.json",
        "generation_config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
    }
)
_REQUIRED_CHECKPOINT_FILES = frozenset(_SAFE_CHECKPOINT_FILES - {"LICENSE"})

COACT_HWE_PROMPT = """You are a HWE observation compressor. Preserve the public evidence needed
for the next tool call while making the current observation shorter.

## Public task goal
{task_goal}

## Executed tool call
{tool_call}

## Observation type
{observation_type}

## Current compact observation (display line numbers are prompt-only)
{observation}

Return exactly one JSON object with fields `type` and `content`.
Use `{{\"type\":\"unchanged\",\"content\":null}}` when shortening is unsafe.
Use `{{\"type\":\"plain\",\"content\":\"...\"}}` for a faithful plain summary.
Use `{{\"type\":\"code\",\"content\":[\"N-M:reason\"]}}` only to omit clearly
irrelevant display-numbered lines; the ranges refer to the unnumbered observation and all
other lines remain verbatim.
The result must not be longer than the current observation. Keep diagnostics, line ranges, paths,
and exact evidence needed for HWE repair.
"""


class CoactCandidateGenerator(Protocol):
    """Generate one text response for a fixed compression seed."""

    def generate(self, prompt: str, *, seed: int, max_new_tokens: int) -> str: ...


@dataclass(frozen=True)
class CoactCheckpointFile:
    name: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class CoactCheckpointLock:
    """Content lock for the official local-only compressor checkpoint."""

    model_id: str
    revision: str
    weight_size_bytes: int
    files: tuple[CoactCheckpointFile, ...]
    tokenizer_files: tuple[str, ...]
    prompt_hash: str
    license_status: str = "model_card_license_not_declared"
    source_repository: str = "THU-Agent/CoACT"
    source_repository_license: str = "MIT"
    remote_code: bool = False
    lock_hash: str = ""

    def __post_init__(self) -> None:
        if self.model_id != COACT_CHECKPOINT_MODEL_ID or self.revision != COACT_CHECKPOINT_REVISION:
            raise ValueError("CoACT checkpoint identity is not the frozen official revision")
        if self.weight_size_bytes != COACT_WEIGHT_SIZE_BYTES:
            raise ValueError("CoACT safetensors size differs from the frozen checkpoint")
        if self.remote_code is not False:
            raise ValueError("CoACT remote code must remain disabled")
        if not self.lock_hash:
            object.__setattr__(self, "lock_hash", content_hash(self.as_dict(include_hash=False)))
        elif content_hash(self.as_dict(include_hash=False)) != self.lock_hash:
            raise ValueError("CoACT checkpoint lock identity changed")

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "model_id": self.model_id,
            "revision": self.revision,
            "weight_size_bytes": self.weight_size_bytes,
            "files": [file.__dict__ for file in self.files],
            "tokenizer_files": list(self.tokenizer_files),
            "prompt_hash": self.prompt_hash,
            "license_status": self.license_status,
            "source_repository": self.source_repository,
            "source_repository_license": self.source_repository_license,
            "remote_code": self.remote_code,
        }
        if include_hash:
            value["lock_hash"] = self.lock_hash
        return value


@dataclass(frozen=True)
class CoactParsedCandidate:
    kind: str
    content: str | list[str] | None
    effective_text: str
    normalized_response: str


@dataclass(frozen=True)
class CoactCandidateAudit:
    seed: int
    response_hash: str
    candidate_hash: str | None
    kind: str | None
    token_count: int | None
    accepted: bool
    reason: str
    nap: dict[str, Any] | None


@dataclass(frozen=True)
class CoactEntryResult:
    """Selected replacement and all candidate-gate decisions for one observation."""

    sequence: int
    action: str
    observation_type: str
    original_sha256: str
    selected_sha256: str
    original_tokens: int
    selected_tokens: int
    selected_kind: str
    changed: bool
    fallback: bool
    fallback_reason: str | None
    candidate_audits: tuple[CoactCandidateAudit, ...]
    result_hash: str = ""

    def __post_init__(self) -> None:
        if self.selected_tokens > self.original_tokens:
            raise ValueError("CoACT selected observation grew in tokens")
        if not self.result_hash:
            object.__setattr__(self, "result_hash", content_hash(self.as_dict(include_hash=False)))
        elif content_hash(self.as_dict(include_hash=False)) != self.result_hash:
            raise ValueError("CoACT entry result identity changed")

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "sequence": self.sequence,
            "action": self.action,
            "observation_type": self.observation_type,
            "original_sha256": self.original_sha256,
            "selected_sha256": self.selected_sha256,
            "original_tokens": self.original_tokens,
            "selected_tokens": self.selected_tokens,
            "selected_kind": self.selected_kind,
            "changed": self.changed,
            "fallback": self.fallback,
            "fallback_reason": self.fallback_reason,
            "candidate_audits": [audit.__dict__ for audit in self.candidate_audits],
        }
        if include_hash:
            value["result_hash"] = self.result_hash
        return value


def render_coact_prompt(
    *,
    task_goal: str,
    tool_call: Mapping[str, Any],
    observation_type: str,
    observation: str,
) -> str:
    """Render a prompt whose data fields are intentionally public-only."""

    return COACT_HWE_PROMPT.format(
        task_goal=task_goal.strip(),
        tool_call=json.dumps(dict(tool_call), sort_keys=True, separators=(",", ":")),
        observation_type=observation_type,
        observation=_number_observation_lines(observation),
    )


def parse_coact_response(raw_response: str, *, original_text: str) -> CoactParsedCandidate | None:
    """Parse unchanged/plain/code JSON and reconstruct code omissions safely."""

    cleaned = raw_response.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
    try:
        payload = json.loads(cleaned)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"type", "content"}:
        return None
    kind = payload.get("type")
    content = payload.get("content")
    if kind == "unchanged" and content is None:
        return CoactParsedCandidate("unchanged", None, original_text, _json_response(kind, content))
    if kind == "plain" and isinstance(content, str) and content.strip():
        return CoactParsedCandidate("plain", content, content, _json_response(kind, content))
    if kind != "code" or not isinstance(content, list) or not content:
        return None
    lines = original_text.splitlines()
    ranges: list[tuple[int, int, str | None]] = []
    for item in content:
        if not isinstance(item, str):
            return None
        match = _RANGE.fullmatch(item.strip())
        if match is None:
            return None
        start = int(match.group("start"))
        end = int(match.group("end") or match.group("start"))
        if start > end or end > len(lines):
            return None
        ranges.append((start, end, match.group("summary") or None))
    ranges.sort()
    if any(ranges[index][0] <= ranges[index - 1][1] for index in range(1, len(ranges))):
        return None
    output: list[str] = []
    current = 1
    for start, end, summary in ranges:
        output.extend(lines[current - 1 : start - 1])
        count = end - start + 1
        output.append(
            f"(compressed {count} lines: {summary})" if summary else f"(compressed {count} lines)"
        )
        current = end + 1
    output.extend(lines[current - 1 :])
    effective = "\n".join(output)
    return CoactParsedCandidate(
        "code", [str(item) for item in content], effective, _json_response(kind, content)
    )


def validate_coact_candidate(
    candidate: CoactParsedCandidate,
    *,
    original_text: str,
    counter: TokenCounter,
    action: str,
    metadata: Mapping[str, Any],
) -> tuple[bool, str]:
    """Apply token, structure and HWE diagnostic preservation checks."""

    if candidate.kind == "unchanged":
        return True, "unchanged"
    if not candidate.effective_text.strip():
        return False, "empty_candidate"
    if counter.count(candidate.effective_text) > counter.count(original_text):
        return False, "token_count_increased"
    if candidate.kind == "code" and not _code_structure_is_valid(
        original_text, candidate.effective_text
    ):
        return False, "code_structure_changed"
    required = _required_evidence(original_text, action=action, metadata=metadata)
    missing = [value for value in required if value and value not in candidate.effective_text]
    if missing:
        return False, "diagnostic_evidence_missing"
    return True, "accepted"


def build_coact_checkpoint_lock(checkpoint_root: Path) -> dict[str, Any]:
    """Hash the official checkpoint and its public prompt/tokenizer files, fail closed."""

    root = _safe_directory(checkpoint_root, label="CoACT checkpoint")
    files: list[CoactCheckpointFile] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name == ".cache" and path.is_dir() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("CoACT checkpoint contains a symlink or unexpected directory")
        if path.name not in _SAFE_CHECKPOINT_FILES:
            raise ValueError(f"CoACT checkpoint contains unexpected file {path.name!r}")
        files.append(
            CoactCheckpointFile(
                path.name,
                path.stat().st_size,
                _sha256_file(path),
            )
        )
    names = {item.name for item in files}
    missing = _REQUIRED_CHECKPOINT_FILES - names
    if missing:
        raise ValueError("CoACT checkpoint is missing " + ", ".join(sorted(missing)))
    weights = next(item for item in files if item.name == "model.safetensors")
    if weights.size_bytes != COACT_WEIGHT_SIZE_BYTES:
        raise ValueError("CoACT model.safetensors does not match the official 8.4GB lock")
    tokenizer_files = tuple(
        sorted(
            name
            for name in names
            if name in {"tokenizer.json", "tokenizer_config.json", "chat_template.jinja"}
        )
    )
    lock = CoactCheckpointLock(
        model_id=COACT_CHECKPOINT_MODEL_ID,
        revision=COACT_CHECKPOINT_REVISION,
        weight_size_bytes=weights.size_bytes,
        files=tuple(files),
        tokenizer_files=tokenizer_files,
        prompt_hash=content_hash({"prompt_id": COACT_FORMAT_ID, "prompt": COACT_HWE_PROMPT}),
        license_status="model_card_license_not_declared",
        source_repository="THU-Agent/CoACT",
        source_repository_license="MIT",
    )
    return lock.as_dict()


def compress_hwe_trajectory(
    transcript: Mapping[str, Any],
    *,
    task_goal: str,
    counter: TokenCounter,
    generator: CoactCandidateGenerator | Callable[..., str],
    nap_validator: AnchorNapValidator,
    max_candidates: int = COACT_MAX_CANDIDATES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compress each tool observation once, in order, and return the sealed public layer."""

    if max_candidates != COACT_MAX_CANDIDATES:
        raise ValueError("CoACT candidate count is frozen to eight seeds")
    source = transcript.get("sft_messages")
    outcomes = transcript.get("compaction_manifest", {}).get("step_outcomes")
    if not isinstance(source, list) or not isinstance(outcomes, list):
        raise ValueError("CoACT source transcript lacks messages or step outcomes")
    messages = [copy.deepcopy(message) for message in source]
    original_messages = [copy.deepcopy(message) for message in source]
    audits: list[CoactEntryResult] = []
    sequence = 0
    pending_call: dict[str, Any] | None = None
    for index, message in enumerate(messages):
        if message.get("role") == "assistant" and message.get("tool_calls"):
            calls = message.get("tool_calls")
            if not isinstance(calls, list) or len(calls) != 1:
                raise ValueError("CoACT requires one ordered assistant tool call")
            function = calls[0].get("function") if isinstance(calls[0], Mapping) else None
            if not isinstance(function, Mapping):
                raise ValueError("CoACT encountered a malformed tool call")
            pending_call = {"name": function.get("name"), "arguments": function.get("arguments")}
            continue
        if message.get("role") != "tool":
            continue
        if pending_call is None or not isinstance(message.get("content"), str):
            raise ValueError("CoACT tool observation is not causally paired")
        if sequence >= len(outcomes):
            raise ValueError("CoACT outcomes do not cover the source trajectory")
        outcome = outcomes[sequence]
        if outcome.get("sequence") != sequence or outcome.get("action") != pending_call.get("name"):
            raise ValueError("CoACT outcome order differs from source actions")
        original = message["content"]
        action = str(pending_call["name"])
        observation_type = _observation_type(action, original)
        original_tokens = counter.count(original)
        selected = original
        selected_kind = "unchanged"
        fallback_reason: str | None = None
        candidate_audits: list[CoactCandidateAudit] = []
        if original_tokens <= COACT_BYPASS_TOKENS:
            fallback_reason = "below_512_token_bypass"
        elif action == "finish":
            fallback_reason = "terminal_observation_no_next_action"
        else:
            prompt = render_coact_prompt(
                task_goal=task_goal,
                tool_call=pending_call,
                observation_type=observation_type,
                observation=original,
            )
            candidates: list[tuple[int, CoactParsedCandidate]] = []
            for seed in COACT_CANDIDATE_SEEDS:
                raw = _generate(generator, prompt, seed=seed, max_new_tokens=512)
                parsed = parse_coact_response(raw, original_text=original)
                if parsed is None:
                    candidate_audits.append(
                        CoactCandidateAudit(
                            seed,
                            hash_bytes(raw.encode()),
                            None,
                            None,
                            None,
                            False,
                            "parse_failed",
                            None,
                        )
                    )
                    continue
                valid, reason = validate_coact_candidate(
                    parsed,
                    original_text=original,
                    counter=counter,
                    action=action,
                    metadata=outcome,
                )
                if not valid:
                    candidate_audits.append(
                        CoactCandidateAudit(
                            seed,
                            hash_bytes(raw.encode()),
                            hash_bytes(parsed.effective_text.encode()),
                            parsed.kind,
                            counter.count(parsed.effective_text),
                            False,
                            reason,
                            None,
                        )
                    )
                    continue
                candidate_context = [copy.deepcopy(item) for item in messages[: index + 1]]
                candidate_context[-1]["content"] = parsed.effective_text
                baseline_context = [copy.deepcopy(item) for item in messages[: index + 1]]
                baseline_context[-1]["content"] = original
                nap = nap_validator.validate(baseline_context, candidate_context)
                candidate_audits.append(
                    CoactCandidateAudit(
                        seed,
                        hash_bytes(raw.encode()),
                        hash_bytes(parsed.effective_text.encode()),
                        parsed.kind,
                        counter.count(parsed.effective_text),
                        nap.passed,
                        "nap_passed" if nap.passed else "nap_failed",
                        nap.as_dict(),
                    )
                )
                if nap.passed:
                    candidates.append((seed, parsed))
            if candidates:
                _, best = min(
                    candidates, key=lambda item: (counter.count(item[1].effective_text), item[0])
                )
                selected = best.effective_text
                selected_kind = best.kind
            else:
                fallback_reason = "no_candidate_passed_all_gates"
        message["content"] = selected
        entry = CoactEntryResult(
            sequence=sequence,
            action=action,
            observation_type=observation_type,
            original_sha256=hash_bytes(original.encode()),
            selected_sha256=hash_bytes(selected.encode()),
            original_tokens=original_tokens,
            selected_tokens=counter.count(selected),
            selected_kind=selected_kind,
            changed=selected != original,
            fallback=selected == original and fallback_reason is not None,
            fallback_reason=fallback_reason,
            candidate_audits=tuple(candidate_audits),
        )
        audits.append(entry)
        pending_call = None
        sequence += 1
    if pending_call is not None or sequence != len(outcomes):
        raise ValueError("CoACT source transcript and outcomes are not exactly aligned")
    _validate_causal_replacement(original_messages, messages)
    manifest_base = {
        "format_id": COACT_FORMAT_ID,
        "strategy": "observation_entry_once_permanent_replacement",
        "bypass_tokens": COACT_BYPASS_TOKENS,
        "candidate_seeds": list(COACT_CANDIDATE_SEEDS),
        "max_candidates": COACT_MAX_CANDIDATES,
        "max_length": COACT_MAX_LENGTH,
        "entries": [entry.as_dict() for entry in audits],
        "source_messages_hash": content_hash(original_messages),
        "compressed_messages_hash": content_hash(messages),
        "causal_validation": "passed",
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
    }
    return messages, {**manifest_base, "manifest_hash": content_hash(manifest_base)}


def validate_coact_messages(
    source_messages: Sequence[Mapping[str, Any]], compressed_messages: Sequence[Mapping[str, Any]]
) -> None:
    """Ensure compression changed only tool contents and preserved all action chronology."""

    if len(source_messages) != len(compressed_messages):
        raise ValueError("CoACT changed the number of messages")
    for original, compressed in zip(source_messages, compressed_messages, strict=True):
        left = {key: value for key, value in original.items() if key != "content"}
        right = {key: value for key, value in compressed.items() if key != "content"}
        if left != right:
            raise ValueError("CoACT changed an action, tool-call ID, role, or workspace metadata")


def build_coact_dataset_manifest(examples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Seal exactly eight complete CoACT examples and their canonical action multiset."""

    if len(examples) != 8:
        raise ValueError("CoACT HWE dataset requires exactly eight trajectories")
    hashes: list[str] = []
    task_ids: list[str] = []
    action_hashes: list[str] = []
    token_counts: list[int] = []
    for example in examples:
        if example.get("format_id") != COACT_EXAMPLE_FORMAT_ID:
            raise ValueError("CoACT dataset contains a foreign example format")
        identity = dict(example)
        expected = identity.pop("example_hash", None)
        if not isinstance(expected, str) or content_hash(identity) != expected:
            raise ValueError("CoACT example identity changed")
        task_id = example.get("task_id")
        if not isinstance(task_id, str) or task_id in task_ids:
            raise ValueError("CoACT requires eight distinct task IDs")
        task_ids.append(task_id)
        hashes.append(expected)
        tokens = example.get("token_count")
        if not isinstance(tokens, int) or tokens > COACT_MAX_LENGTH:
            raise ValueError("CoACT example exceeds the 64K no-truncation bound")
        token_counts.append(tokens)
        actions = example.get("canonical_action_hashes")
        if not isinstance(actions, list) or any(not isinstance(item, str) for item in actions):
            raise ValueError("CoACT example omits canonical action hashes")
        action_hashes.extend(actions)
    if len(action_hashes) != 419:
        raise ValueError("CoACT action multiset must contain exactly 419 target actions")
    base = {
        "schema_version": "1.0",
        "format_id": COACT_DATASET_FORMAT_ID,
        "trajectory_count": 8,
        "record_count": 8,
        "task_ids": sorted(task_ids),
        "example_hashes": hashes,
        "canonical_action_hashes": sorted(action_hashes),
        "total_action_count": len(action_hashes),
        "max_token_count": max(token_counts),
        "max_length": COACT_MAX_LENGTH,
        "truncation": "error",
        "training_semantics": "complete_multiturn_assistant_actions",
        "supervised_roles": ["assistant"],
        "observation_compression_format": COACT_FORMAT_ID,
        "only_verifier_resolved": True,
        "only_infrastructure_valid": True,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "hpc_jobs_submitted": False,
    }
    return {**base, "dataset_hash": content_hash(base)}


def seal_coact_example(
    transcript: Mapping[str, Any],
    *,
    compressed_messages: Sequence[Mapping[str, Any]],
    compression_manifest: Mapping[str, Any],
    binding: Mapping[str, Any],
    token_count: int,
) -> dict[str, Any]:
    """Create one complete, verifier-bound CoACT SFT record."""

    if token_count > COACT_MAX_LENGTH:
        raise ValueError("CoACT trajectory exceeds 64K and cannot be truncated")
    if transcript.get("primary_eligible") not in {True, False}:
        raise ValueError("CoACT source transcript has no eligibility identity")
    for key in ("sample_id", "task_hash", "source_hash", "candidate_hash", "verifier_hash"):
        value = binding.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"CoACT binding {key} must be SHA-256")
    source_messages = transcript.get("sft_messages")
    if not isinstance(source_messages, list):
        raise ValueError("CoACT transcript lacks source SFT messages")
    validate_coact_messages(source_messages, compressed_messages)
    actions = canonical_actions_from_messages(compressed_messages)
    base = {
        "schema_version": "1.0",
        "format_id": COACT_EXAMPLE_FORMAT_ID,
        "sample_id": binding["sample_id"],
        "task_id": transcript.get("task_id"),
        "task_hash": binding["task_hash"],
        "source_hash": binding["source_hash"],
        "candidate_hash": binding["candidate_hash"],
        "verifier_hash": binding["verifier_hash"],
        "source_transcript_hash": transcript.get("transcript_hash"),
        "messages": [copy.deepcopy(message) for message in compressed_messages],
        "token_count": token_count,
        "max_length": COACT_MAX_LENGTH,
        "truncation": "error",
        "supervised_roles": ["assistant"],
        "masked_roles": ["system", "user", "tool"],
        "canonical_action_hashes": actions,
        "compression_manifest": dict(compression_manifest),
        "verifier_resolved": True,
        "infrastructure_valid": True,
        "primary_source_eligible": transcript.get("primary_eligible"),
        "raw_provider_events_exported": False,
        "raw_observations_exported": False,
        "private_reasoning_exported": False,
        "hidden_assets_exported": False,
        "reference_solutions_exported": False,
        "credential_values_exported": False,
        "raw_host_paths_exported": False,
    }
    if not isinstance(base["task_id"], str) or not isinstance(base["source_transcript_hash"], str):
        raise ValueError("CoACT transcript omits task identity")
    return {**base, "example_hash": content_hash(base)}


def canonical_actions_from_messages(messages: Sequence[Mapping[str, Any]]) -> list[str]:
    """Extract canonical tool-action hashes in message order."""

    from verigym.hwe.nap import canonical_action_hash

    result: list[str] = []
    for message in messages:
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        calls = message.get("tool_calls")
        if not isinstance(calls, list) or len(calls) != 1:
            raise ValueError("HWE trajectories require one assistant action per turn")
        call = calls[0]
        function = call.get("function") if isinstance(call, Mapping) else None
        if not isinstance(function, Mapping):
            raise ValueError("HWE assistant action is malformed")
        result.append(
            canonical_action_hash(
                {"name": function.get("name"), "arguments": function.get("arguments")}
            )
        )
    return result


def _generate(
    generator: CoactCandidateGenerator | Callable[..., str],
    prompt: str,
    *,
    seed: int,
    max_new_tokens: int,
) -> str:
    if hasattr(generator, "generate"):
        generated = generator.generate(prompt, seed=seed, max_new_tokens=max_new_tokens)
    else:
        generated = generator(prompt, seed=seed, max_new_tokens=max_new_tokens)
    if not isinstance(generated, str):
        raise ValueError("CoACT generator returned a non-text response")
    return generated


def _json_response(kind: str, content: object) -> str:
    return json.dumps({"type": kind, "content": content}, ensure_ascii=False, separators=(",", ":"))


def _number_observation_lines(observation: str) -> str:
    lines = observation.splitlines()
    if len(lines) <= 1:
        return observation
    return "\n".join(f"{index}: {line}" for index, line in enumerate(lines, start=1))


def _code_structure_is_valid(original: str, candidate: str) -> bool:
    original_lines = original.splitlines()
    candidate_lines = candidate.splitlines()
    original_set = set(original_lines)
    return all(line.startswith("(compressed ") or line in original_set for line in candidate_lines)


def _required_evidence(original: str, *, action: str, metadata: Mapping[str, Any]) -> list[str]:
    required: list[str] = []
    exit_code = metadata.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        required.append(str(exit_code))
    changed_paths = metadata.get("changed_paths")
    if isinstance(changed_paths, list):
        required.extend(path for path in changed_paths if isinstance(path, str))
    lines = original.splitlines()
    diagnostic_lines = [line.strip() for line in lines if _DIAGNOSTIC.search(line)]
    if diagnostic_lines:
        required.append(diagnostic_lines[0])
    if action in {"apply_patch", "inspect_diff"}:
        required.extend(line.strip() for line in lines if line.startswith(("@@", "+++", "---")))
    if not required and _HEADER_FIELD.search(original):
        required.extend(field for field in ("exit_code", "changed_paths") if field in original)
    return list(dict.fromkeys(value for value in required if value))


def _observation_type(action: str, content: str) -> str:
    if action in {"apply_patch", "inspect_diff"} or "@@" in content:
        return "diff"
    if action == "read_file":
        return "code"
    if action == "list_files":
        return "listing"
    if action == "shell":
        return "diagnostic_or_command_output"
    return "tool_result"


def _validate_causal_replacement(
    source_messages: Sequence[Mapping[str, Any]], compressed_messages: Sequence[Mapping[str, Any]]
) -> None:
    validate_coact_messages(source_messages, compressed_messages)
    source_tools = [message for message in source_messages if message.get("role") == "tool"]
    compressed_tools = [message for message in compressed_messages if message.get("role") == "tool"]
    if len(source_tools) != len(compressed_tools):
        raise ValueError("CoACT changed the number of tool observations")


def _safe_directory(path: Path, *, label: str) -> Path:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a non-symlink directory")
    return path.resolve(strict=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "COACT_BYPASS_TOKENS",
    "COACT_CANDIDATE_SEEDS",
    "COACT_CHECKPOINT_MODEL_ID",
    "COACT_CHECKPOINT_REVISION",
    "COACT_DATASET_FORMAT_ID",
    "COACT_EXAMPLE_FORMAT_ID",
    "COACT_FORMAT_ID",
    "COACT_HWE_PROMPT",
    "COACT_MAX_CANDIDATES",
    "COACT_MAX_LENGTH",
    "COACT_WEIGHT_SIZE_BYTES",
    "CoactCandidateAudit",
    "CoactCandidateGenerator",
    "CoactCheckpointLock",
    "CoactEntryResult",
    "CoactParsedCandidate",
    "build_coact_checkpoint_lock",
    "build_coact_dataset_manifest",
    "canonical_actions_from_messages",
    "compress_hwe_trajectory",
    "parse_coact_response",
    "render_coact_prompt",
    "seal_coact_example",
    "validate_coact_candidate",
    "validate_coact_messages",
]
