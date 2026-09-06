"""Frozen feedback-v2 specification and mutation-qualification contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from verigym.plugin_api import ConfigurationError

from .known_bad import known_bad_source, task_specific_bad_source
from .manifest import ALL_TASK_NAMES

MUTATION_COUNT_PER_TASK = 12


@dataclass(frozen=True)
class SpecificationObligation:
    """One public-specification behavior that a task's smoke must exercise."""

    kind: str
    description: str


@dataclass(frozen=True)
class MutationControl:
    """One compile-shaped, independently identified negative qualification case."""

    mutation_id: str
    obligation: str
    base_control: str
    task_specific: bool
    description: str


_SEQUENTIAL_TASKS = frozenset(
    {
        "accu",
        "adder_pipe_64bit",
        "radix2_div",
        "multi_16bit",
        "multi_booth_8bit",
        "multi_pipe_4bit",
        "multi_pipe_8bit",
        "float_multi",
        "JC_counter",
        "counter_12",
        "ring_counter",
        "up_down_counter",
        "fsm",
        "sequence_detector",
        "LIFObuffer",
        "LFSR",
        "right_shifter",
        "freq_div",
        "freq_divbyeven",
        "freq_divbyfrac",
        "freq_divbyodd",
        "calendar",
        "edge_detect",
        "parallel2serial",
        "pulse_detect",
        "serial2parallel",
        "synchronizer",
        "traffic_light",
        "width_8to16",
        "RAM",
        "instr_reg",
        "pe",
        "signal_generator",
        "square_wave",
        "asyn_fifo",
    }
)
_ENABLE_HANDSHAKE_TASKS = frozenset(
    {
        "accu",
        "adder_pipe_64bit",
        "radix2_div",
        "multi_16bit",
        "multi_booth_8bit",
        "multi_pipe_4bit",
        "multi_pipe_8bit",
        "counter_12",
        "LIFObuffer",
        "parallel2serial",
        "pulse_detect",
        "serial2parallel",
        "synchronizer",
        "traffic_light",
        "width_8to16",
        "RAM",
        "instr_reg",
        "pe",
        "asyn_fifo",
    }
)
_ORDERING_TASKS = frozenset(
    {
        "adder_pipe_64bit",
        "multi_pipe_4bit",
        "multi_pipe_8bit",
        "LIFObuffer",
        "barrel_shifter",
        "right_shifter",
        "parallel2serial",
        "serial2parallel",
        "width_8to16",
        "RAM",
        "ROM",
        "instr_reg",
        "asyn_fifo",
    }
)
_WIDTH_SIGN_TASKS = frozenset(
    {
        name
        for name in ALL_TASK_NAMES
        if name.startswith(("adder", "multi", "fixed_point", "comparator", "div", "sub"))
    }
    | {"accu", "radix2_div", "float_multi", "alu", "pe", "width_8to16"}
)
_OVERFLOW_WRAP_TASKS = frozenset(
    {
        "accu",
        "adder_16bit",
        "adder_32bit",
        "adder_8bit",
        "adder_bcd",
        "adder_pipe_64bit",
        "fixed_point_adder",
        "fixed_point_substractor",
        "sub_64bit",
        "JC_counter",
        "counter_12",
        "ring_counter",
        "up_down_counter",
        "calendar",
        "asyn_fifo",
    }
)

_OBLIGATION_TEXT = {
    "nominal": "Representative values produce the specified nominal result.",
    "reset_initial": "Reset or initial state has the specified polarity, value, and recovery.",
    "boundary": "Minimum, maximum, empty, full, or transition boundaries are exercised.",
    "enable_handshake": "Disabled or back-pressured operations do not update architectural state.",
    "latency": "Outputs and validity indications occur at the specified cycle or edge.",
    "ordering": "Buffered, pipelined, shifted, or serialized values preserve specified ordering.",
    "width_sign": "Widths, extension, truncation, and signed interpretation match the interface.",
    "overflow_wrap": (
        "Carry, overflow, wrap-around, or saturation behavior matches the specification."
    ),
    "state_transition": "State changes and holds follow the complete transition conditions.",
}


def _task_obligations(name: str) -> tuple[SpecificationObligation, ...]:
    kinds = ["nominal", "boundary"]
    if name in _SEQUENTIAL_TASKS or name == "clkgenerator":
        kinds.append("reset_initial")
    if name in _ENABLE_HANDSHAKE_TASKS:
        kinds.append("enable_handshake")
    if name in _SEQUENTIAL_TASKS:
        kinds.extend(("latency", "state_transition"))
    if name in _ORDERING_TASKS:
        kinds.append("ordering")
    if name in _WIDTH_SIGN_TASKS:
        kinds.append("width_sign")
    if name in _OVERFLOW_WRAP_TASKS:
        kinds.append("overflow_wrap")
    return tuple(
        SpecificationObligation(kind=kind, description=_OBLIGATION_TEXT[kind])
        for kind in _OBLIGATION_TEXT
        if kind in kinds
    )


SPECIFICATION_OBLIGATIONS = {name: _task_obligations(name) for name in ALL_TASK_NAMES}

_CONTROL_MUTATIONS = (
    MutationControl(
        "stuck-zero",
        "nominal",
        "stuck-zero",
        False,
        "All observable results are held at zero.",
    ),
    MutationControl(
        "reset-error",
        "reset_initial",
        "reset-error",
        False,
        "Reset polarity, reset state, or initial behavior is incorrect.",
    ),
    MutationControl(
        "protocol-latency-error",
        "latency",
        "protocol-latency-error",
        False,
        "The response is generated at an incorrect protocol phase or latency.",
    ),
    MutationControl(
        "functional-error",
        "nominal",
        "functional-error",
        False,
        "The nominal function computes a deliberately incorrect result.",
    ),
)
_TASK_MUTATION_SHAPES = (
    ("boundary-off-by-one", "boundary", "functional-error"),
    ("enable-ignored", "enable_handshake", "protocol-latency-error"),
    ("latency-shift", "latency", "protocol-latency-error"),
    ("ordering-reversed", "ordering", "functional-error"),
    ("width-truncated", "width_sign", "stuck-zero"),
    ("signedness-flipped", "width_sign", "functional-error"),
    ("overflow-wrap-error", "overflow_wrap", "reset-error"),
    ("state-transition-error", "state_transition", "functional-error"),
)


def _task_mutations(name: str) -> tuple[MutationControl, ...]:
    fallback = tuple(item.kind for item in SPECIFICATION_OBLIGATIONS[name])
    obligations = set(fallback)
    task_specific = tuple(
        MutationControl(
            mutation_id=mutation_id,
            obligation=obligation if obligation in obligations else fallback[index % len(fallback)],
            base_control=base,
            task_specific=True,
            description=f"{name}: deliberate {mutation_id.replace('-', ' ')} specification error.",
        )
        for index, (mutation_id, obligation, base) in enumerate(_TASK_MUTATION_SHAPES)
    )
    return _CONTROL_MUTATIONS + task_specific


MUTATION_CONTROLS = {name: _task_mutations(name) for name in ALL_TASK_NAMES}


def feedback_v2_mutant_source(name: str, mutation_id: str) -> str:
    """Return a compile-shaped, observable control without reading the golden implementation."""

    try:
        mutation = next(item for item in MUTATION_CONTROLS[name] if item.mutation_id == mutation_id)
    except (KeyError, StopIteration) as exc:
        raise ConfigurationError(f"unknown RTLLM feedback-v2 mutant: {name}/{mutation_id}") from exc
    source = known_bad_source(name, mutation.base_control)
    if not mutation.task_specific:
        return source
    return task_specific_bad_source(
        name,
        mutation_id=mutation_id,
        obligation=mutation.obligation,
        base_control=mutation.base_control,
    )


def feedback_v2_mutant_sources_payload() -> dict[str, object]:
    """Return the frozen source digest map separately from task identity metadata."""

    return {
        "schema_version": "rtllm-feedback-v2-mutant-sources-v1",
        "tasks": {
            name: {
                mutation.mutation_id: hashlib.sha256(
                    feedback_v2_mutant_source(name, mutation.mutation_id).encode()
                ).hexdigest()
                for mutation in MUTATION_CONTROLS[name]
            }
            for name in ALL_TASK_NAMES
        },
    }


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def feedback_v2_catalog_payload() -> dict[str, object]:
    return {
        "schema_version": "rtllm-feedback-v2-qualification-v1",
        "tasks": {
            name: {
                "obligations": [asdict(item) for item in SPECIFICATION_OBLIGATIONS[name]],
                "mutations": [asdict(item) for item in MUTATION_CONTROLS[name]],
            }
            for name in ALL_TASK_NAMES
        },
    }


FEEDBACK_V2_CATALOG_SHA256 = "b4576feb8e980bcbd7aad7517e88b37ac07afc18ef73557b9ce38530da46f69d"
FEEDBACK_V2_MUTANT_SOURCES_SHA256 = (
    "1356493bd8609fbd4f9998b48500646a184ae1a194787a984767dfe25551b29c"
)


def validate_feedback_v2_catalog() -> None:
    if set(SPECIFICATION_OBLIGATIONS) != set(ALL_TASK_NAMES):
        raise RuntimeError("RTLLM feedback-v2 obligations do not cover the frozen inventory")
    if set(MUTATION_CONTROLS) != set(ALL_TASK_NAMES):
        raise RuntimeError("RTLLM feedback-v2 mutations do not cover the frozen inventory")
    for name, mutations in MUTATION_CONTROLS.items():
        if len(mutations) != MUTATION_COUNT_PER_TASK:
            raise RuntimeError(f"RTLLM feedback-v2 mutation count differs for {name}")
        if len({item.mutation_id for item in mutations}) != len(mutations):
            raise RuntimeError(f"RTLLM feedback-v2 mutation IDs are not unique for {name}")
        if sum(item.task_specific for item in mutations) < 4:
            raise RuntimeError(f"RTLLM feedback-v2 lacks task-specific mutations for {name}")
    actual = _canonical_hash(feedback_v2_catalog_payload())
    if FEEDBACK_V2_CATALOG_SHA256 != "TO_BE_FROZEN" and actual != FEEDBACK_V2_CATALOG_SHA256:
        raise RuntimeError("RTLLM feedback-v2 catalog differs from its frozen identity")
    source_actual = _canonical_hash(feedback_v2_mutant_sources_payload())
    if (
        FEEDBACK_V2_MUTANT_SOURCES_SHA256 != "TO_BE_FROZEN"
        and source_actual != FEEDBACK_V2_MUTANT_SOURCES_SHA256
    ):
        raise RuntimeError("RTLLM feedback-v2 mutant sources differ from their frozen identity")


validate_feedback_v2_catalog()


__all__ = [
    "FEEDBACK_V2_CATALOG_SHA256",
    "FEEDBACK_V2_MUTANT_SOURCES_SHA256",
    "MUTATION_CONTROLS",
    "MUTATION_COUNT_PER_TASK",
    "SPECIFICATION_OBLIGATIONS",
    "MutationControl",
    "SpecificationObligation",
    "feedback_v2_catalog_payload",
    "feedback_v2_mutant_source",
    "feedback_v2_mutant_sources_payload",
    "validate_feedback_v2_catalog",
]
