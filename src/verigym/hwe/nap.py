"""Typed next-action-preservation (NAP) validation for HWE artifacts.

The original HWE masking experiment deliberately stopped at structural causal checks.  This
module adds the next, independent gate used by the training-ready experiment: a frozen base
agent samples eight actions on the uncompressed context and one deterministic action on a
candidate context.  The candidate passes only when the mean of the three best typed-action
similarities reaches the frozen threshold.

The validator is provider-neutral.  Production callers inject a local Qwen predictor; unit tests
can inject a tiny deterministic predictor without importing a model-serving stack.  An exact
identity between the uncompressed and candidate contexts is accepted through a separate,
auditable structural path.  This keeps the gate reflexive: a lossless no-op must not fail merely
because a temperature-0 decode differs from a stochastic anchor sample.
"""

from __future__ import annotations

import copy
import html
import json
import re
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from verigym.core.hashing import content_hash
from verigym.hwe.profiles import canonical_hwe_action_json

NAP_FORMAT_ID = "verigym_hwe_nap_validation_v2"
NAP_ANCHOR_COUNT = 8
NAP_TOP_K = 3
NAP_SIMILARITY_THRESHOLD = 0.6
NAP_ANCHOR_SEEDS = tuple(range(NAP_ANCHOR_COUNT))
NAP_ANCHOR_TEMPERATURE = 0.7
NAP_COMPRESSED_TEMPERATURE = 0.0

_ACTION_NAMES = frozenset(
    {"list_files", "read_file", "apply_patch", "shell", "inspect_diff", "finish"}
)
_WHITESPACE = re.compile(r"\s+")
_SHELL_LINE_RANGE = re.compile(r"^(?P<start>\d+)(?:,(?P<end>\d+))?p?$")
_XML_TOOL_CALL = re.compile(
    r"<tool_call>\s*<function=(?P<name>[a-z_]+)>(?P<body>.*?)</function>\s*</tool_call>",
    re.DOTALL,
)
_XML_PARAMETER = re.compile(
    r"<parameter=(?P<name>[a-z_]+)>\s*(?P<value>.*?)\s*</parameter>", re.DOTALL
)
_XML_PARAMETER_START = re.compile(r"<parameter=(?P<name>[a-z_]+)>", re.DOTALL)
_SEARCH_TERM = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


@dataclass(frozen=True)
class _SearchCommandSignature:
    """Conservative signature for one read-only grep/rg inspection command."""

    tool: str
    terms: frozenset[str]
    paths: frozenset[str]
    output_range: tuple[int, int] | None


class HweActionPredictor(Protocol):
    """Minimal local predictor interface required by :class:`AnchorNapValidator`."""

    def predict_action(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float,
        seed: int,
    ) -> object: ...


class HweBatchActionPredictor(Protocol):
    """Optional batched interface used to parallelize frozen anchor sampling."""

    def predict_actions(
        self,
        messages: Sequence[Sequence[Mapping[str, Any]]],
        *,
        temperatures: Sequence[float],
        seeds: Sequence[int],
    ) -> Sequence[object]: ...


class NapUnavailable(RuntimeError):
    """Raised when a training-ready gate was requested without a real predictor."""


@dataclass(frozen=True)
class HweTypedAction:
    """A parsed HWE native-shell action with canonical arguments."""

    name: str
    arguments: dict[str, Any]

    def canonical_json(self) -> str:
        return canonical_hwe_action_json(self.name, self.arguments, profile_id="hwe_standard_v2")

    @property
    def action_hash(self) -> str:
        return content_hash(json.loads(self.canonical_json()))

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": copy.deepcopy(self.arguments)}


@dataclass(frozen=True)
class NapValidationResult:
    """Auditable result for one candidate context."""

    format_id: str
    anchor_count: int
    anchor_seeds: tuple[int, ...]
    anchor_temperature: float
    compressed_temperature: float
    threshold: float
    top_k: int
    anchor_actions: tuple[dict[str, Any], ...]
    candidate_action: dict[str, Any] | None
    similarities: tuple[float, ...]
    top_k_score: float
    passed: bool
    predictor_calls: int
    failure_reason: str | None = None
    validation_mode: str = "anchor"
    validation_hash: str = ""

    def __post_init__(self) -> None:
        if self.anchor_count != len(self.anchor_seeds) or self.anchor_count != len(
            self.anchor_actions
        ):
            raise ValueError("NAP anchor count and samples disagree")
        if len(self.similarities) != self.anchor_count:
            raise ValueError("NAP similarity count and samples disagree")
        if self.top_k != NAP_TOP_K or self.anchor_count != NAP_ANCHOR_COUNT:
            raise ValueError("NAP uses a frozen eight-anchor/top-three gate")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("NAP threshold must be in [0, 1]")
        if any(not 0.0 <= score <= 1.0 for score in self.similarities):
            raise ValueError("NAP similarity scores must be in [0, 1]")
        if self.validation_mode not in {"anchor", "identity_exact"}:
            raise ValueError("NAP validation mode is unsupported")
        if self.validation_mode == "identity_exact":
            if not self.passed or self.predictor_calls != 0 or self.candidate_action is not None:
                raise ValueError("exact-identity NAP must be a predictor-free pass")
            if self.top_k_score != 1.0 or any(score != 1.0 for score in self.similarities):
                raise ValueError("exact-identity NAP must carry a perfect structural score")
        if not self.validation_hash:
            identity = self.as_dict(include_hash=False)
            object.__setattr__(self, "validation_hash", content_hash(identity))
        elif content_hash(self.as_dict(include_hash=False)) != self.validation_hash:
            raise ValueError("NAP validation identity changed")

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "format_id": self.format_id,
            "anchor_count": self.anchor_count,
            "anchor_seeds": list(self.anchor_seeds),
            "anchor_temperature": self.anchor_temperature,
            "compressed_temperature": self.compressed_temperature,
            "threshold": self.threshold,
            "top_k": self.top_k,
            "anchor_actions": [copy.deepcopy(item) for item in self.anchor_actions],
            "candidate_action": copy.deepcopy(self.candidate_action),
            "similarities": list(self.similarities),
            "top_k_score": self.top_k_score,
            "passed": self.passed,
            "predictor_calls": self.predictor_calls,
            "failure_reason": self.failure_reason,
            "validation_mode": self.validation_mode,
        }
        if include_hash:
            value["validation_hash"] = self.validation_hash
        return value


def canonical_action_hash(value: object) -> str:
    """Return the canonical hash used to compare actions across both training arms."""

    action = parse_hwe_action(value)
    if action is None:
        raise ValueError("value is not a canonical HWE action")
    return action.action_hash


def parse_hwe_action(value: object) -> HweTypedAction | None:
    """Parse model/tool-call-shaped data into one validated HWE action.

    A predictor may return a native function-call mapping, an OpenAI assistant message, the
    repository-action envelope, or a JSON string.  Malformed output is intentionally represented
    as ``None`` so a NAP gate fails closed instead of treating prose as an action.
    """

    if isinstance(value, HweTypedAction):
        return value
    candidate: object = value
    if isinstance(candidate, str):
        raw_text = candidate
        try:
            candidate = json.loads(raw_text)
        except json.JSONDecodeError:
            embedded = _parse_embedded_json(raw_text)
            if embedded is not None:
                return embedded
            return _parse_xml_tool_call(raw_text)
    if isinstance(candidate, Mapping):
        if isinstance(candidate.get("tool_calls"), list) and candidate["tool_calls"]:
            return parse_hwe_action(candidate["tool_calls"][0])
        if isinstance(candidate.get("function"), Mapping):
            function = candidate["function"]
            return _action_from_name_arguments(function.get("name"), function.get("arguments"))
        if "action" in candidate and "arguments" in candidate:
            return _action_from_name_arguments(candidate.get("action"), candidate.get("arguments"))
        if "name" in candidate and "arguments" in candidate:
            return _action_from_name_arguments(candidate.get("name"), candidate.get("arguments"))
    return None


def typed_action_similarity(left: object, right: object) -> float:
    """Compare two HWE actions while respecting typed argument semantics."""

    first = parse_hwe_action(left)
    second = parse_hwe_action(right)
    if first is None or second is None or first.name != second.name:
        return 0.0
    if first.name in {"apply_patch", "finish", "inspect_diff"}:
        return float(first.arguments == second.arguments)
    if first.name == "shell":
        command_score = _shell_command_similarity(
            first.arguments.get("command"), second.arguments.get("command")
        )
        cwd_score = float(
            _normalize_cwd(first.arguments.get("cwd"))
            == _normalize_cwd(second.arguments.get("cwd"))
        )
        return 0.8 * command_score + 0.2 * cwd_score
    if first.name == "list_files":
        return float(
            _normalize_path(first.arguments.get("path"))
            == _normalize_path(second.arguments.get("path"))
        )
    if first.name == "read_file":
        path_score = float(
            _normalize_path(first.arguments.get("path"))
            == _normalize_path(second.arguments.get("path"))
        )
        start_score = float(
            _integer_or_default(first.arguments.get("start_line"), 1)
            == _integer_or_default(second.arguments.get("start_line"), 1)
        )
        end_score = float(
            _integer_or_none(first.arguments.get("end_line"))
            == _integer_or_none(second.arguments.get("end_line"))
        )
        return 0.6 * path_score + 0.2 * start_score + 0.2 * end_score
    return float(first.arguments == second.arguments)


def top_three_action_similarity(similarities: Sequence[float]) -> float:
    """Aggregate anchor similarities using the frozen CoACT top-three mean."""

    if not similarities:
        return 0.0
    return sum(sorted((float(value) for value in similarities), reverse=True)[:NAP_TOP_K]) / min(
        NAP_TOP_K, len(similarities)
    )


class AnchorNapValidator:
    """Run the frozen eight-anchor NAP gate against an injected local predictor."""

    def __init__(
        self,
        predictor: HweActionPredictor | Callable[..., object],
        *,
        anchor_seeds: Sequence[int] = NAP_ANCHOR_SEEDS,
        anchor_temperature: float = NAP_ANCHOR_TEMPERATURE,
        compressed_temperature: float = NAP_COMPRESSED_TEMPERATURE,
        threshold: float = NAP_SIMILARITY_THRESHOLD,
    ) -> None:
        if tuple(anchor_seeds) != NAP_ANCHOR_SEEDS:
            raise ValueError("NAP anchor seeds are frozen to 0..7")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("NAP threshold must be in [0, 1]")
        self.predictor = predictor
        self.anchor_seeds = NAP_ANCHOR_SEEDS
        self.anchor_temperature = anchor_temperature
        self.compressed_temperature = compressed_temperature
        self.threshold = threshold
        self._prediction_cache: dict[tuple[str, float, int], object] = {}

    def validate(
        self,
        uncompressed_messages: Sequence[Mapping[str, Any]],
        compressed_messages: Sequence[Mapping[str, Any]],
    ) -> NapValidationResult:
        if list(uncompressed_messages) == list(compressed_messages):
            return self._identity_pass()
        contexts = [uncompressed_messages for _ in self.anchor_seeds]
        contexts.append(compressed_messages)
        temperatures = [self.anchor_temperature for _ in self.anchor_seeds]
        temperatures.append(self.compressed_temperature)
        seeds = list(self.anchor_seeds) + [0]
        raw_outputs = self._predict_many(contexts, temperatures=temperatures, seeds=seeds)
        if len(raw_outputs) != len(contexts):
            raise NapUnavailable("batched NAP predictor returned the wrong number of actions")
        anchors: list[HweTypedAction] = []
        for raw in raw_outputs[:NAP_ANCHOR_COUNT]:
            action = parse_hwe_action(raw)
            if action is None:
                return self._failed(
                    anchors, None, "anchor_action_parse_failed", predictor_calls=len(contexts)
                )
            anchors.append(action)
        raw_candidate = raw_outputs[-1]
        candidate = parse_hwe_action(raw_candidate)
        if candidate is None:
            return self._failed(anchors, None, "candidate_action_parse_failed", predictor_calls=9)
        similarities = tuple(typed_action_similarity(candidate, anchor) for anchor in anchors)
        score = top_three_action_similarity(similarities)
        passed = score >= self.threshold
        return NapValidationResult(
            format_id=NAP_FORMAT_ID,
            anchor_count=NAP_ANCHOR_COUNT,
            anchor_seeds=self.anchor_seeds,
            anchor_temperature=self.anchor_temperature,
            compressed_temperature=self.compressed_temperature,
            threshold=self.threshold,
            top_k=NAP_TOP_K,
            anchor_actions=tuple(anchor.as_dict() for anchor in anchors),
            candidate_action=candidate.as_dict(),
            similarities=similarities,
            top_k_score=score,
            passed=passed,
            predictor_calls=9,
            failure_reason=None if passed else "similarity_below_threshold",
            validation_mode="anchor",
        )

    def _identity_pass(self) -> NapValidationResult:
        """Accept an exact no-op without confusing stochasticity for information loss.

        This is a structural proof, not a relaxed action-similarity threshold.  The candidate
        context is byte/structure-identical to the reference context, so no model call is needed
        to establish that the observation transformation preserved the model-visible history.
        Non-identical contexts continue through the frozen eight-anchor/top-three gate above.
        """

        return NapValidationResult(
            format_id=NAP_FORMAT_ID,
            anchor_count=NAP_ANCHOR_COUNT,
            anchor_seeds=self.anchor_seeds,
            anchor_temperature=self.anchor_temperature,
            compressed_temperature=self.compressed_temperature,
            threshold=self.threshold,
            top_k=NAP_TOP_K,
            anchor_actions=tuple({} for _ in self.anchor_seeds),
            candidate_action=None,
            similarities=tuple(1.0 for _ in self.anchor_seeds),
            top_k_score=1.0,
            passed=True,
            predictor_calls=0,
            failure_reason=None,
            validation_mode="identity_exact",
        )

    def _predict(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float,
        seed: int,
    ) -> object:
        predictor = self.predictor
        if hasattr(predictor, "predict_action"):
            return predictor.predict_action(messages, temperature=temperature, seed=seed)
        if callable(predictor):
            return predictor(messages, temperature=temperature, seed=seed)
        raise NapUnavailable("NAP validator has no callable local predictor")

    def _predict_many(
        self,
        messages: Sequence[Sequence[Mapping[str, Any]]],
        *,
        temperatures: Sequence[float],
        seeds: Sequence[int],
    ) -> list[object]:
        predictor = self.predictor
        batch_predict = getattr(predictor, "predict_actions", None)
        results: list[Any] = [None] * len(messages)
        missing: list[tuple[int, tuple[str, float, int], Sequence[Mapping[str, Any]]]] = []
        for index, (context, temperature, seed) in enumerate(
            zip(messages, temperatures, seeds, strict=True)
        ):
            key = (content_hash(list(context)), float(temperature), int(seed))
            if key in self._prediction_cache:
                results[index] = self._prediction_cache[key]
            else:
                missing.append((index, key, context))
        if missing:
            if callable(batch_predict):
                generated = list(
                    batch_predict(
                        [item[2] for item in missing],
                        temperatures=[temperatures[item[0]] for item in missing],
                        seeds=[seeds[item[0]] for item in missing],
                    )
                )
            else:
                generated = [
                    self._predict(
                        context,
                        temperature=temperatures[index],
                        seed=seeds[index],
                    )
                    for index, _, context in missing
                ]
            if len(generated) != len(missing):
                raise NapUnavailable("batched NAP predictor returned the wrong number of actions")
            for (index, key, _), value in zip(missing, generated, strict=True):
                self._prediction_cache[key] = value
                results[index] = value
        return list(results)

    def _failed(
        self,
        anchors: Sequence[HweTypedAction],
        candidate: HweTypedAction | None,
        reason: str,
        *,
        predictor_calls: int,
    ) -> NapValidationResult:
        padded_actions = [action.as_dict() for action in anchors]
        padded_actions.extend({} for _ in range(NAP_ANCHOR_COUNT - len(padded_actions)))
        similarities = tuple(0.0 for _ in range(NAP_ANCHOR_COUNT))
        return NapValidationResult(
            format_id=NAP_FORMAT_ID,
            anchor_count=NAP_ANCHOR_COUNT,
            anchor_seeds=self.anchor_seeds,
            anchor_temperature=self.anchor_temperature,
            compressed_temperature=self.compressed_temperature,
            threshold=self.threshold,
            top_k=NAP_TOP_K,
            anchor_actions=tuple(padded_actions),
            candidate_action=candidate.as_dict() if candidate else None,
            similarities=similarities,
            top_k_score=0.0,
            passed=False,
            predictor_calls=predictor_calls,
            failure_reason=reason,
            validation_mode="anchor",
        )


def _action_from_name_arguments(name: object, arguments: object) -> HweTypedAction | None:
    if not isinstance(name, str) or name not in _ACTION_NAMES:
        return None
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    if not isinstance(arguments, Mapping):
        return None
    try:
        canonical = canonical_hwe_action_json(name, dict(arguments), profile_id="hwe_standard_v2")
        payload = json.loads(canonical)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return HweTypedAction(name=name, arguments=dict(payload["arguments"]))


def _parse_xml_tool_call(value: object) -> HweTypedAction | None:
    if not isinstance(value, str):
        return None
    match = _XML_TOOL_CALL.search(value)
    if match is None:
        # Qwen's native chat template may stop immediately after a function or parameter
        # without emitting the optional closing ``</tool_call>`` wrapper.  The function name and
        # any closed (or end-of-generation) parameters are still an auditable typed action; do
        # not require a closing tag that the bounded decoder was unable to produce.
        match = re.search(
            r"<tool_call>\s*<function=(?P<name>[a-z_]+)>(?P<body>.*)",
            value,
            re.DOTALL,
        )
    if match is None:
        return None
    body = re.split(r"</function>|</tool_call>", match.group("body"), maxsplit=1)[0]
    arguments: dict[str, Any] = {}
    parameter_starts = list(_XML_PARAMETER_START.finditer(body))
    for index, parameter in enumerate(parameter_starts):
        value_start = parameter.end()
        value_end = (
            parameter_starts[index + 1].start() if index + 1 < len(parameter_starts) else len(body)
        )
        raw_value = body[value_start:value_end].split("</parameter>", 1)[0]
        raw = html.unescape(raw_value).strip()
        parsed: object = raw
        if raw[:1] in {"{", "[", '"'} or parameter.group("name") in {
            "start_line",
            "end_line",
        }:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
        arguments[parameter.group("name")] = parsed
    return _action_from_name_arguments(match.group("name"), arguments)


def _parse_embedded_json(value: str) -> HweTypedAction | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(value):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            continue
        action = parse_hwe_action(payload)
        if action is not None:
            return action
    return None


def _normalize_shell_command(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    try:
        return " ".join(shlex.split(normalized, posix=True))
    except ValueError:
        return _WHITESPACE.sub(" ", normalized)


def _shell_command_similarity(left: object, right: object) -> float:
    """Compare normalized shell commands with bounded read-only inspection equivalence.

    HWE agents commonly vary only the end of a ``sed -n 'start,endp'`` inspection range.  Such
    actions address the same file and nearby evidence, so treating them as unrelated commands
    makes the frozen top-three NAP aggregate impossible to pass when the anchor sample contains
    one exact and one adjacent inspection.  The same applies to a grep/rg search when the
    read-only command addresses the same file set and the search terms overlap.  Every other
    command remains exact: this is not a general fuzzy command metric and never makes different
    paths or unrelated search queries similar.
    """

    left_normalized = _normalize_shell_command(left)
    right_normalized = _normalize_shell_command(right)
    if left_normalized == right_normalized:
        return 1.0
    try:
        left_tokens = shlex.split(left_normalized, posix=True)
        right_tokens = shlex.split(right_normalized, posix=True)
    except ValueError:
        return 0.0
    if len(left_tokens) != len(right_tokens):
        return _search_command_similarity(left_normalized, right_normalized)
    range_scores: list[float] = []
    for left_token, right_token in zip(left_tokens, right_tokens, strict=True):
        if left_token == right_token:
            continue
        left_range = _parse_shell_line_range(left_token)
        right_range = _parse_shell_line_range(right_token)
        if left_range is None or right_range is None:
            return _search_command_similarity(left_normalized, right_normalized)
        range_scores.append(_line_range_overlap(left_range, right_range))
    return sum(range_scores) / len(range_scores) if range_scores else 0.0


def _search_command_similarity(left: str, right: str) -> float:
    """Score only same-target, read-only grep/rg searches with overlapping query terms."""

    first = _parse_search_command(left)
    second = _parse_search_command(right)
    if first is None or second is None:
        return 0.0
    if not (first.terms & second.terms):
        return 0.0
    tool_score = 1.0 if first.tool == second.tool else 0.9
    path_score = _search_path_containment(first.paths, second.paths)
    if path_score == 0.0:
        return 0.0
    term_union = first.terms | second.terms
    term_score = len(first.terms & second.terms) / len(term_union)
    output_score = _search_output_range_similarity(first.output_range, second.output_range)
    # The query terms dominate.  Tool and path identity keep this auditable and prevent a
    # coincidental common word from making searches over unrelated files equivalent.
    return 0.2 * tool_score + 0.25 * path_score + 0.45 * term_score + 0.1 * output_score


def _parse_search_command(command: str) -> _SearchCommandSignature | None:
    try:
        stages = _split_shell_pipeline(shlex.split(command, posix=True))
    except ValueError:
        return None
    if not stages:
        return None
    first = stages[0]
    if not first:
        return None
    tool = first[0].rsplit("/", 1)[-1]
    if tool not in {"grep", "rg"}:
        return None
    pattern: str | None = None
    paths: list[str] = []
    index = 1
    options_ended = False
    while index < len(first):
        token = first[index]
        if not options_ended and token == "--":
            options_ended = True
            index += 1
            continue
        if not options_ended and token in {"-e", "--regexp"}:
            if pattern is not None or index + 1 >= len(first):
                return None
            pattern = first[index + 1]
            index += 2
            continue
        if not options_ended and token.startswith("-"):
            index += 1
            continue
        if pattern is None:
            pattern = token
        else:
            paths.append(token)
        index += 1
    if not pattern or not paths or any(path.startswith("-") for path in paths):
        return None
    terms = frozenset(
        term for term in (item.lower() for item in _SEARCH_TERM.findall(pattern)) if len(term) > 1
    )
    if not terms:
        return None
    output_range: tuple[int, int] | None = None
    for stage in stages[1:]:
        if not stage:
            return None
        stage_tool = stage[0].rsplit("/", 1)[-1]
        if stage_tool == "sed":
            ranges = [
                parsed for token in stage if (parsed := _parse_shell_line_range(token)) is not None
            ]
            if len(ranges) != 1:
                return None
            output_range = ranges[0]
        elif stage_tool == "head":
            numbers = [
                int(stage[index + 1])
                for index, token in enumerate(stage[:-1])
                if token in {"-n", "--lines"} and stage[index + 1].isdigit()
            ]
            if len(numbers) != 1:
                return None
            output_range = (1, numbers[0])
        else:
            return None
    return _SearchCommandSignature(
        tool=tool,
        terms=terms,
        paths=frozenset(_normalize_path(path) for path in paths),
        output_range=output_range,
    )


def _split_shell_pipeline(tokens: Sequence[str]) -> list[list[str]]:
    stages: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            stages.append([])
        else:
            stages[-1].append(token)
    return stages


def _search_path_containment(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right or not (left & right):
        return 0.0
    if left <= right or right <= left:
        return 1.0
    return len(left & right) / max(len(left), len(right))


def _search_output_range_similarity(
    left: tuple[int, int] | None, right: tuple[int, int] | None
) -> float:
    if left is None and right is None:
        return 1.0
    if left is None or right is None:
        return 0.5
    return _line_range_overlap(left, right)


def _parse_shell_line_range(value: str) -> tuple[int, int] | None:
    if "," not in value and not value.endswith("p"):
        return None
    match = _SHELL_LINE_RANGE.fullmatch(value)
    if match is None:
        return None
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    return (start, end) if start <= end else None


def _line_range_overlap(left: tuple[int, int], right: tuple[int, int]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]) + 1)
    union = max(left[1], right[1]) - min(left[0], right[0]) + 1
    return intersection / union if union else 0.0


def _normalize_cwd(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "."
    return _WHITESPACE.sub(" ", value.strip()).rstrip("/") or "/"


def _normalize_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "."
    return value.strip().replace("\\", "/").rstrip("/") or "/"


def _integer_or_default(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _integer_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "AnchorNapValidator",
    "HweActionPredictor",
    "HweBatchActionPredictor",
    "HweTypedAction",
    "NAP_ANCHOR_COUNT",
    "NAP_ANCHOR_SEEDS",
    "NAP_ANCHOR_TEMPERATURE",
    "NAP_COMPRESSED_TEMPERATURE",
    "NAP_FORMAT_ID",
    "NAP_SIMILARITY_THRESHOLD",
    "NAP_TOP_K",
    "NapUnavailable",
    "NapValidationResult",
    "canonical_action_hash",
    "parse_hwe_action",
    "top_three_action_similarity",
    "typed_action_similarity",
]
