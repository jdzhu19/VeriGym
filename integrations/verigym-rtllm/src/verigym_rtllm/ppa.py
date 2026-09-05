"""Frozen RTLLM PPA47 task bindings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from .manifest import ALL_TASK_NAMES, TASK_MANIFESTS

PPA47_EXCLUSION_REASONS = {
    "float_multi": "reference_non_synthesizable_event_control",
    "synchronizer": "reference_multiple_edge_drivers",
    "clkgenerator": "reference_zero_cell_delay_model",
}


@dataclass(frozen=True)
class PpaTaskBinding:
    """Complete per-task synthesis identity without site-owned asset paths."""

    task_name: str
    top: str
    source_path: str
    eligible: bool
    exclusion_reason: str | None
    clock_mode: str | None
    clocks: tuple[tuple[str, float], ...]
    sdc: str | None
    power_base_clock: str | None
    reference_normalization: str | None
    reference_normalized_sha256: str | None


_SINGLE_CLOCKS = {
    "accu": "clk",
    "adder_pipe_64bit": "clk",
    "radix2_div": "clk",
    "multi_16bit": "clk",
    "multi_booth_8bit": "clk",
    "multi_pipe_4bit": "clk",
    "multi_pipe_8bit": "clk",
    "JC_counter": "clk",
    "counter_12": "clk",
    "ring_counter": "clk",
    "up_down_counter": "clk",
    "fsm": "CLK",
    "sequence_detector": "clk",
    "LIFObuffer": "Clk",
    "LFSR": "clk",
    "right_shifter": "clk",
    "freq_div": "CLK_in",
    "freq_divbyeven": "clk",
    "freq_divbyfrac": "clk",
    "freq_divbyodd": "clk",
    "calendar": "CLK",
    "edge_detect": "clk",
    "parallel2serial": "clk",
    "pulse_detect": "clk",
    "serial2parallel": "clk",
    "traffic_light": "clk",
    "width_8to16": "clk",
    "RAM": "clk",
    "instr_reg": "clk",
    "pe": "clk",
    "signal_generator": "clk",
    "square_wave": "clk",
}

_REFERENCE_NORMALIZATIONS = {
    "sequence_detector": (
        "dc_ver134_combinational_blocking_assignment_v1",
        "da9720d113e7b248230569f6e707273e99d16645645b55e83d2276f2a8554ffd",
    ),
    "ROM": (
        "dc_ver281_fixed_rom_case_v1",
        "484b9dcd649a2aac9c8a5801fc3c6f52af066b07c3aab3e5767f3b914a817d02",
    ),
}


def _single_clock_sdc(clock: str) -> str:
    return f"create_clock -name {clock} -period 10 [get_ports {clock}]\n"


def _combinational_sdc() -> str:
    return (
        "create_clock -name virtual_clk -period 10\n"
        "set_input_delay 1 -clock virtual_clk [all_inputs]\n"
        "set_output_delay 1 -clock virtual_clk [all_outputs]\n"
    )


def _binding(name: str) -> PpaTaskBinding:
    manifest = TASK_MANIFESTS[name]
    normalization = _REFERENCE_NORMALIZATIONS.get(name, (None, None))
    reason = PPA47_EXCLUSION_REASONS.get(name)
    if reason is not None:
        return PpaTaskBinding(
            task_name=name,
            top=manifest.synthesis_top,
            source_path=f"rtl/{name}.v",
            eligible=False,
            exclusion_reason=reason,
            clock_mode=None,
            clocks=(),
            sdc=None,
            power_base_clock=None,
            reference_normalization=normalization[0],
            reference_normalized_sha256=normalization[1],
        )
    if name == "asyn_fifo":
        return PpaTaskBinding(
            task_name=name,
            top=manifest.synthesis_top,
            source_path=f"rtl/{name}.v",
            eligible=True,
            exclusion_reason=None,
            clock_mode="asynchronous_dual_clock",
            clocks=(("wclk", 10.0), ("rclk", 14.0)),
            sdc=(
                "create_clock -name wclk -period 10 [get_ports wclk]\n"
                "create_clock -name rclk -period 14 [get_ports rclk]\n"
                "set_clock_groups -asynchronous -group [get_clocks wclk] "
                "-group [get_clocks rclk]\n"
            ),
            power_base_clock="wclk",
            reference_normalization=normalization[0],
            reference_normalized_sha256=normalization[1],
        )
    clock = _SINGLE_CLOCKS.get(name)
    if clock is not None:
        return PpaTaskBinding(
            task_name=name,
            top=manifest.synthesis_top,
            source_path=f"rtl/{name}.v",
            eligible=True,
            exclusion_reason=None,
            clock_mode="single_clock",
            clocks=((clock, 10.0),),
            sdc=_single_clock_sdc(clock),
            power_base_clock=clock,
            reference_normalization=normalization[0],
            reference_normalized_sha256=normalization[1],
        )
    return PpaTaskBinding(
        task_name=name,
        top=manifest.synthesis_top,
        source_path=f"rtl/{name}.v",
        eligible=True,
        exclusion_reason=None,
        clock_mode="combinational_virtual_clock",
        clocks=(("virtual_clk", 10.0),),
        sdc=_combinational_sdc(),
        power_base_clock="virtual_clk",
        reference_normalization=normalization[0],
        reference_normalized_sha256=normalization[1],
    )


PPA_TASK_BINDINGS = {name: _binding(name) for name in ALL_TASK_NAMES}
PPA47_TASK_NAMES = tuple(name for name in ALL_TASK_NAMES if PPA_TASK_BINDINGS[name].eligible)
PPA47_BINDINGS_SHA256 = "7ce5dc1bbfc01fe0de19ed64f895da705830ced601789ded2054f3e59bd486ae"


def ppa47_bindings_payload() -> dict[str, object]:
    return {
        "schema_version": "rtllm-ppa-task-bindings-v1",
        "tasks": {name: asdict(PPA_TASK_BINDINGS[name]) for name in ALL_TASK_NAMES},
    }


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_ppa47_bindings() -> None:
    if set(PPA_TASK_BINDINGS) != set(ALL_TASK_NAMES):
        raise RuntimeError("RTLLM PPA bindings do not cover the frozen inventory")
    if len(PPA47_TASK_NAMES) != 47:
        raise RuntimeError("RTLLM PPA47 must contain exactly 47 eligible tasks")
    excluded = {
        name: binding.exclusion_reason
        for name, binding in PPA_TASK_BINDINGS.items()
        if not binding.eligible
    }
    if excluded != PPA47_EXCLUSION_REASONS:
        raise RuntimeError("RTLLM PPA exclusions differ from the frozen contract")
    for name in PPA47_TASK_NAMES:
        binding = PPA_TASK_BINDINGS[name]
        if not all((binding.sdc, binding.clock_mode, binding.power_base_clock)):
            raise RuntimeError(f"RTLLM PPA binding is incomplete: {name}")
        if (binding.reference_normalization is None) != (
            binding.reference_normalized_sha256 is None
        ):
            raise RuntimeError(f"RTLLM PPA reference normalization is incomplete: {name}")
    actual = _canonical_hash(ppa47_bindings_payload())
    if PPA47_BINDINGS_SHA256 != "TO_BE_FROZEN" and actual != PPA47_BINDINGS_SHA256:
        raise RuntimeError("RTLLM PPA47 bindings differ from their frozen identity")


validate_ppa47_bindings()


__all__ = [
    "PPA47_BINDINGS_SHA256",
    "PPA47_EXCLUSION_REASONS",
    "PPA47_TASK_NAMES",
    "PPA_TASK_BINDINGS",
    "PpaTaskBinding",
    "ppa47_bindings_payload",
    "validate_ppa47_bindings",
]
