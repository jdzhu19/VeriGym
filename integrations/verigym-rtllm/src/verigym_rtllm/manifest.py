"""Frozen RTLLM 2.0 source inventory and task-level adapter metadata."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FrozenTaskTree:
    file_count: int
    files_hash: str


@dataclass(frozen=True)
class ClockConstraint:
    name: str
    period_ns: float


@dataclass(frozen=True)
class RTLLMTaskManifest:
    name: str
    root: str
    title: str
    prompt_file: str
    reference_file: str
    testbench_file: str
    auxiliary_files: tuple[str, ...]
    candidate_top: str
    reference_module: str
    testbench_top: str
    pass_marker: str
    fail_marker: str
    synthesis_top: str
    clocks: tuple[ClockConstraint, ...]
    power_base_clock: str
    file_hashes: tuple[tuple[str, str], ...]
    testbench_projection: str = "identity-v1"
    testbench_projection_sha256: str | None = None

    @property
    def expected_hashes(self) -> dict[str, str]:
        return {f"{self.root}/{name}": digest for name, digest in self.file_hashes}


FROZEN_TASK_TREES: dict[str, FrozenTaskTree] = {
    "Arithmetic/Accumulator/accu": FrozenTaskTree(
        4, "28a8e721297643313800a7331759b2d85dc6b0e8ac247a5dab5aadc2331de6a5"
    ),
    "Arithmetic/Adder/adder_16bit": FrozenTaskTree(
        4, "19f5c6f7829a2a3e2f669df0bf4f59600be00a9098d8b2c26ca445966aeb8bbb"
    ),
    "Arithmetic/Adder/adder_32bit": FrozenTaskTree(
        4, "04a7891f43b109914655e222345c47ce13d2af789b284beb96f188f198750432"
    ),
    "Arithmetic/Adder/adder_8bit": FrozenTaskTree(
        4, "4fc386e06389f111c8ee2ad0f42224b90b4d1c5db60ab75851e9a509ae99618f"
    ),
    "Arithmetic/Adder/adder_bcd": FrozenTaskTree(
        4, "eb41848ca706bdd83edfccdbccd33981e9a23a12651365bc014c818d4cd70da7"
    ),
    "Arithmetic/Adder/adder_pipe_64bit": FrozenTaskTree(
        4, "12832c9c9db14bc2e009b9d4035bd0059cc5b4f466ec4dd87b0ca63487c321a8"
    ),
    "Arithmetic/Comparator/comparator_3bit": FrozenTaskTree(
        4, "a42e2352aedbf26097666519acb20503fa54ce51978d4cb7cef1e743dacf8219"
    ),
    "Arithmetic/Comparator/comparator_4bit": FrozenTaskTree(
        4, "2385836317fc8f92fe5ff00b65156ca879b112e398e25733fb7389f266c3d7a4"
    ),
    "Arithmetic/Divider/div_16bit": FrozenTaskTree(
        4, "c8906dc0df049b1cec96a4ff1d04945e542052b100dcf3bc6a54d8dc56e4f77d"
    ),
    "Arithmetic/Divider/radix2_div": FrozenTaskTree(
        4, "5bdd7925ed446d8a1dc9af411c39678066064b873e651d1a28b6e01b48d7ef64"
    ),
    "Arithmetic/Multiplier/multi_16bit": FrozenTaskTree(
        4, "aa026fabc2619f540d832062bb0b06653a463995256df194461b42b124eeea4b"
    ),
    "Arithmetic/Multiplier/multi_8bit": FrozenTaskTree(
        4, "f6ffc733dedbb3f3cadb2015acdeef094188eb1d27fb8eb265dd9c4de2ff1ed0"
    ),
    "Arithmetic/Multiplier/multi_booth_8bit": FrozenTaskTree(
        5, "8a244494390a62b5bc7a70cce32d47a5232c8da6ecd55eb7c8eea93325f6ca1e"
    ),
    "Arithmetic/Multiplier/multi_pipe_4bit": FrozenTaskTree(
        4, "5a0183d99b5505349e0e8165b9ef76f6fa9a399e5deac7824ff21cd4f65cd238"
    ),
    "Arithmetic/Multiplier/multi_pipe_8bit": FrozenTaskTree(
        4, "cd91cff872c0ab58d7650bb083d0b7ba9ec6a9d59d64dfef1ee44f96406f31fa"
    ),
    "Arithmetic/Other/fixed_point_adder": FrozenTaskTree(
        4, "da49d289ba3e67edd4fd09b4b61de99044a6eb7d1e2457e9604756a01d053e0d"
    ),
    "Arithmetic/Other/fixed_point_substractor": FrozenTaskTree(
        4, "90b4eadb2765ab9195704b13a81e8444b0ee849dedba998af81da1d913ceaef7"
    ),
    "Arithmetic/Other/float_multi": FrozenTaskTree(
        4, "9231a417aaca33ace0a4096daed2df6f9f9dcc079b3250150d79a65885f48c66"
    ),
    "Arithmetic/Substractor/sub_64bit": FrozenTaskTree(
        4, "0891e697c5f44f5288ff638c07e455e6f18af36fefd099b7b86971b9926e2aa0"
    ),
    "Control/Counter/JC_counter": FrozenTaskTree(
        4, "baa265b9a852af707a02d77835dcd2a1a890876a14fda53ece9d1665b26bc1ce"
    ),
    "Control/Counter/counter_12": FrozenTaskTree(
        4, "fb8c330c5b13e546a68461958be9462ea6706ac58bffdd6e35dca561451f2a44"
    ),
    "Control/Counter/ring_counter": FrozenTaskTree(
        4, "4dd30a9ccba2e5f0469f316d9528509997a836a27985a2d56e58e152bc800dbd"
    ),
    "Control/Counter/up_down_counter": FrozenTaskTree(
        4, "9639cd9455e9f0a58715ecf8f8f5df128012f19a5df419a3a9a407f08807276c"
    ),
    "Control/Finite State Machine/fsm": FrozenTaskTree(
        4, "c8b183fdbc50025629426f708f4696833a0a1c615f4551af042d6d5651b5b2a3"
    ),
    "Control/Finite State Machine/sequence_detector": FrozenTaskTree(
        4, "c6f6a1c795f6af48efce694ccd4f9ad41f5f52f1502bf8e74273a14b11224b05"
    ),
    "Memory/FIFO/asyn_fifo": FrozenTaskTree(
        7, "a19415cdcabeabd2f779a13ad03d283595e6f9a825da6f46ffed4dd77420d2b2"
    ),
    "Memory/LIFO/LIFObuffer": FrozenTaskTree(
        4, "f1fb453ef878f79fa385ac250a0eb53892eb68a7e4ee7dbd92d95e813d5a3054"
    ),
    "Memory/Shifter/LFSR": FrozenTaskTree(
        4, "68487a3dcb370dbbf67ef762e1f94fe9d7b99437cdf3b881604e0f0fbcf3b358"
    ),
    "Memory/Shifter/barrel_shifter": FrozenTaskTree(
        4, "5bb87a2b15f8a2bb41e615827ae3835bc9a9ba62a8880bcf258c3c62326ccd0c"
    ),
    "Memory/Shifter/right_shifter": FrozenTaskTree(
        4, "39669790ba07bdebd5a3c55afa3953aa7d78279f4e62d7d16cfe3963491434e6"
    ),
    "Miscellaneous/Frequency divider/freq_div": FrozenTaskTree(
        4, "8c24097e9125116a98aec6700f174ddb73fb2316d326de8a385d9385d847c4bc"
    ),
    "Miscellaneous/Frequency divider/freq_divbyeven": FrozenTaskTree(
        4, "e70340c1f2eb0248c381db73fdadcac479c71804c9c0db6253ad31efe3cd6b19"
    ),
    "Miscellaneous/Frequency divider/freq_divbyfrac": FrozenTaskTree(
        4, "d47517d4a1e67b13208545014fb7f9ee25f5b8e19aeb1623e02612697e4e8d73"
    ),
    "Miscellaneous/Frequency divider/freq_divbyodd": FrozenTaskTree(
        4, "fc4a95eedb982b0114c4223869c178b0bceac3b805783a0175cffd0ca9ddaf4e"
    ),
    "Miscellaneous/Others/calendar": FrozenTaskTree(
        5, "0fefba1c97f08fb773dd777cd446e5f6ad0da23a9c0fdf1ff28498c2124fd241"
    ),
    "Miscellaneous/Others/edge_detect": FrozenTaskTree(
        4, "3dc1ae1e4ada8fbef067c55f9f53fbd4910e6172825b29b2ec63c7b9716c8f18"
    ),
    "Miscellaneous/Others/parallel2serial": FrozenTaskTree(
        4, "d5fd53e8f73177a091ab4950dbbc154e8edd6437f37b7550962fce713611eedc"
    ),
    "Miscellaneous/Others/pulse_detect": FrozenTaskTree(
        4, "24645c99645ad28a2582e2c633b5da16c9534820d2b688bf5d201539eff3eeaf"
    ),
    "Miscellaneous/Others/serial2parallel": FrozenTaskTree(
        4, "f150b8cbec5ecd70172dd46597d95b5c4b687b3198ee5c5f6703a66f3dd691ec"
    ),
    "Miscellaneous/Others/synchronizer": FrozenTaskTree(
        4, "324267b8a5d29071024ca306f5ca8c47b7c56c074e9b41dfec0e5e51874a2463"
    ),
    "Miscellaneous/Others/traffic_light": FrozenTaskTree(
        4, "2dd87d178ff595c90c7cbcfa59d14d07929b5bcd9807303ec37e4363c746e646"
    ),
    "Miscellaneous/Others/width_8to16": FrozenTaskTree(
        4, "a4c351ba74b40d9cf05860a53ada71640f66c2c5119dfc2be71df867c6ec1ffe"
    ),
    "Miscellaneous/RISC-V/RAM": FrozenTaskTree(
        4, "111427ed59fafc81af6f320ece4d8785b70a628bf9fabc1cf29ac4ef3ae49d85"
    ),
    "Miscellaneous/RISC-V/ROM": FrozenTaskTree(
        4, "5a836dbc114447ac77451919d44c46d0e9df32ab8a660437e1fc97b8468f33c7"
    ),
    "Miscellaneous/RISC-V/alu": FrozenTaskTree(
        5, "cae6337d055e01a377c030e451f731fd0675a63236a01c2f6aafbd3603b91f01"
    ),
    "Miscellaneous/RISC-V/clkgenerator": FrozenTaskTree(
        4, "5f0b5fd55c6813a7f0dd4c54f8dc520b96cd2c164fcf7a8f98291414d672ed6d"
    ),
    "Miscellaneous/RISC-V/instr_reg": FrozenTaskTree(
        4, "cd8ea3a6b7b6a276fbc634f9aae4c5ed7c4f32538f30b14c5cd83ad5dd936cb3"
    ),
    "Miscellaneous/RISC-V/pe": FrozenTaskTree(
        4, "229715ac6001e19be4bd5c34fd290aee1e7fffa64f067d18fde1a7d9f28d617c"
    ),
    "Miscellaneous/Signal generation/signal_generator": FrozenTaskTree(
        5, "ffcf7a5c22c11fe014deafba2f0eda5f1835411e2beb7edc1b58df0ae521453f"
    ),
    "Miscellaneous/Signal generation/square_wave": FrozenTaskTree(
        4, "4e62dafff746a90841905fd9e36cd9c840a845de3b95671efaf2e62d27e0ea67"
    ),
}

FROZEN_TASK_COUNT = 50
FROZEN_FILE_COUNT = 207
FROZEN_TASK_TREES_HASH = "ca6c86e761b14074e738b7ae90a6bc5f4ff02bcc7f2f7f51bb5c67fd3856814c"
FROZEN_DATASET_FILES_HASH = "5877ebc9ab8dbf6aada22a981cd9e087423ea95ce15e527e9cac47122733edda"


TASK_MANIFESTS: dict[str, RTLLMTaskManifest] = {
    "counter_12": RTLLMTaskManifest(
        name="counter_12",
        root="Control/Counter/counter_12",
        title="RTLLM 12-state enabled counter",
        prompt_file="design_description.txt",
        reference_file="verified_counter_12.v",
        testbench_file="testbench.v",
        auxiliary_files=(),
        candidate_top="counter_12",
        reference_module="verified_counter_12",
        testbench_top="counter_12_tb",
        pass_marker="===========Your Design Passed===========",
        fail_marker="===========Failed===========",
        synthesis_top="counter_12",
        clocks=(ClockConstraint("clk", 10.0),),
        power_base_clock="clk",
        file_hashes=(
            (
                "design_description.txt",
                "7619e91759a69d54556766ecf5d370345a9445d279108aa38700258a9cbdfc0e",
            ),
            ("makefile", "a01e995ffe79476648fc6833b86e8a6bf337da3b07d4ed152afa4dce4768e0a8"),
            ("testbench.v", "e47a642c0cece07786ec5d19f417221345fabb9dd22cdd51dbacedd5f731223a"),
            (
                "verified_counter_12.v",
                "e3551f7d82fa522f9e9afe01a2c4ff35bd61143d395f490e17d340cb16a6ae04",
            ),
        ),
    ),
    "up_down_counter": RTLLMTaskManifest(
        name="up_down_counter",
        root="Control/Counter/up_down_counter",
        title="RTLLM 16-bit up/down counter",
        prompt_file="design_description.txt",
        reference_file="verified_up_down_counter.v",
        testbench_file="testbench.v",
        auxiliary_files=(),
        candidate_top="up_down_counter",
        reference_module="up_down_counter",
        testbench_top="testbench",
        pass_marker="=========== Your Design Passed ===========",
        fail_marker="===========Failed===========",
        synthesis_top="up_down_counter",
        clocks=(ClockConstraint("clk", 10.0),),
        power_base_clock="clk",
        file_hashes=(
            (
                "design_description.txt",
                "c14e7e7b9c465d9b65a4e69ea437ca57c76fae5ef9dbd7711aff5765745efcaa",
            ),
            ("makefile", "4ae77da544244cdc15e33b5380321b44e4729e3042c1d14df4ca82e526e7fb7e"),
            ("testbench.v", "d7fde8db2019384d00c5933ebad11757a37f2e21e49c0e778986f57739723f95"),
            (
                "verified_up_down_counter.v",
                "4af9a3fe6a61aefa2e6ba8df99bf10e2f1432a9c2cf460b8267d2ce14e739445",
            ),
        ),
    ),
    "radix2_div": RTLLMTaskManifest(
        name="radix2_div",
        root="Arithmetic/Divider/radix2_div",
        title="RTLLM 8-bit signed and unsigned radix-2 divider",
        prompt_file="design_description.txt",
        reference_file="verified_radix2_div.v",
        testbench_file="testbench.v",
        auxiliary_files=(),
        candidate_top="radix2_div",
        reference_module="verified_radix2_div",
        testbench_top="radix2_div_tb",
        pass_marker="===========Your Design Passed===========",
        fail_marker="===========Failed===========",
        synthesis_top="radix2_div",
        clocks=(ClockConstraint("clk", 10.0),),
        power_base_clock="clk",
        file_hashes=(
            (
                "design_description.txt",
                "b57351ddda568e9f47d43f4df036e149c179a37635b265625f87db13c3367089",
            ),
            ("makefile", "de000712ca864fa1eaf45445b4c954a8536ad78b4c8d105cc85c7e4825d479c2"),
            ("testbench.v", "17859ee47a4d380c1efef7eb7861ce5a7a63935603c75ab77e836e5563955818"),
            (
                "verified_radix2_div.v",
                "d0bb171e8b6b701ca34c40328e8ab1be03995b659726f9c98f88db00796918df",
            ),
        ),
        testbench_projection="edge-aligned-handshake-v1",
        testbench_projection_sha256=(
            "e2549d26295939c79a6ed822c9b91d7770a5044b271911714d9694babf2eeab1"
        ),
    ),
    "multi_pipe_8bit": RTLLMTaskManifest(
        name="multi_pipe_8bit",
        root="Arithmetic/Multiplier/multi_pipe_8bit",
        title="RTLLM pipelined unsigned 8-bit multiplier",
        prompt_file="design_description.txt",
        reference_file="verified_multi_pipe_8bit.v",
        testbench_file="testbench.v",
        auxiliary_files=(),
        candidate_top="multi_pipe_8bit",
        reference_module="verified_multi_pipe_8bit",
        testbench_top="tb_multi_pipe",
        pass_marker="===========Your Design Passed===========",
        fail_marker="===========Failed===========",
        synthesis_top="multi_pipe_8bit",
        clocks=(ClockConstraint("clk", 10.0),),
        power_base_clock="clk",
        file_hashes=(
            (
                "design_description.txt",
                "a44b00ce1bb84f8d91192a599392b52c29800a975af4b4ca13b9d44ff7c72fdc",
            ),
            ("makefile", "4caacbde2dd679cdfd13b9e74e843fcbec099c78a9a124ec6f684587838fbdf1"),
            ("testbench.v", "0a898344f33c3a10d0d49250a050f53ee1c45695cfe73eb4d796b6ec0c70c91a"),
            (
                "verified_multi_pipe_8bit.v",
                "c7b1f309806650b74c998ff3a1c4ae6afd60ebb66f746134aca0bc8ea5928192",
            ),
        ),
    ),
    "LIFObuffer": RTLLMTaskManifest(
        name="LIFObuffer",
        root="Memory/LIFO/LIFObuffer",
        title="RTLLM four-entry 4-bit LIFO buffer",
        prompt_file="design_description.txt",
        reference_file="verified_LIFObuffer.v",
        testbench_file="testbench.v",
        auxiliary_files=(),
        candidate_top="LIFObuffer",
        reference_module="LIFObuffer",
        testbench_top="LIFObuffer_tb",
        pass_marker="=========== Your Design Passed ===========",
        fail_marker="===========Failed===========",
        synthesis_top="LIFObuffer",
        clocks=(ClockConstraint("Clk", 10.0),),
        power_base_clock="Clk",
        file_hashes=(
            (
                "design_description.txt",
                "b87fff407eae035021ef16b20adde0dc44e28d925d3b715f3312ec5c5f88e29d",
            ),
            ("makefile", "86c50b1d8535f798ee5215f64f0db39317b93b8511d033b422d39fa4452770b0"),
            ("testbench.v", "ee713019b9fc692da86e221857e86654d909f3e2c52e0b0813b8fc09550721ce"),
            (
                "verified_LIFObuffer.v",
                "4a5d18d894a4474494e5d06b90d237843b601b05d2cb9acaf532c4f7315bf5a6",
            ),
        ),
    ),
    "asyn_fifo": RTLLMTaskManifest(
        name="asyn_fifo",
        root="Memory/FIFO/asyn_fifo",
        title="RTLLM configurable dual-clock asynchronous FIFO",
        prompt_file="design_description.txt",
        reference_file="verified_asyn_fifo.v",
        testbench_file="testbench.v",
        auxiliary_files=("wfull.txt", "rempty.txt", "tdata.txt"),
        candidate_top="asyn_fifo",
        reference_module="verified_asyn_fifo",
        testbench_top="asyn_fifo_tb",
        pass_marker="===========Your Design Passed===========",
        fail_marker="===========Failed===========",
        synthesis_top="asyn_fifo",
        clocks=(ClockConstraint("wclk", 10.0), ClockConstraint("rclk", 14.0)),
        power_base_clock="wclk",
        file_hashes=(
            (
                "design_description.txt",
                "26037554c6ccc19811444a1bbeb9bc811dd42e8f41de6a2503b906a35f2eab7b",
            ),
            ("makefile", "651afe5cd1e556cc4fc138066e0a96984c32bb50e9d5a802993a138d76f6a977"),
            ("rempty.txt", "d7dfcf7c4aa0b7ee4ff8599fe3f5906265f3b9115e7c236bf9ae0b61736d0adc"),
            ("tdata.txt", "8fcbfdc2b1dc5ffd522e6f48ef160cc1e1e5fe34ec7dbff9946e8a89b61b558a"),
            ("testbench.v", "fe6b07020d96443909b5c65f7db742d25bb9bf066eebc563bbbe6452376a5183"),
            (
                "verified_asyn_fifo.v",
                "a209fc65f57bcda0fa930944653f047a8cd530f3bde5f015e4bebb10c58b1a49",
            ),
            ("wfull.txt", "d2b19da174137eb2de9340c171427f2aaa096215160698afda150c8299dc37d4"),
        ),
        testbench_projection="icarus12-loop-control-v1",
        testbench_projection_sha256=(
            "338b61cb014e7e0f7c4692cf4e7db90bfbd5f723a7da5335c0a84f9ef38bebc7"
        ),
    ),
}

HARDER_TASK_NAMES = ("radix2_div", "multi_pipe_8bit", "LIFObuffer", "asyn_fifo")
ADDITIONAL_TASK_CATALOG_SHA256 = "d1ebca8ae4a8ad05082c8b2ce6f37509af4d0d8e08d08ab3b9c0b5def0c737c4"


def _load_additional_task_manifests() -> dict[str, RTLLMTaskManifest]:
    path = Path(__file__).parent / "assets" / "rtllm_v2_additional_tasks.json"
    catalog = path.read_bytes()
    if hashlib.sha256(catalog).hexdigest() != ADDITIONAL_TASK_CATALOG_SHA256:
        raise RuntimeError("RTLLM task catalog does not match its frozen hash")
    payload: Any = json.loads(catalog)
    if not isinstance(payload, dict) or payload.get("schema_version") != "rtllm-task-catalog-v1":
        raise RuntimeError("RTLLM task catalog schema is unsupported")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list):
        raise RuntimeError("RTLLM task catalog lacks a task list")
    manifests: dict[str, RTLLMTaskManifest] = {}
    for raw in raw_tasks:
        if not isinstance(raw, dict):
            raise RuntimeError("RTLLM task catalog entry is malformed")
        clocks = tuple(
            ClockConstraint(name=clock["name"], period_ns=clock["period_ns"])
            for clock in raw["clocks"]
        )
        manifest = RTLLMTaskManifest(
            name=raw["name"],
            root=raw["root"],
            title=raw["title"],
            prompt_file=raw["prompt_file"],
            reference_file=raw["reference_file"],
            testbench_file=raw["testbench_file"],
            auxiliary_files=tuple(raw["auxiliary_files"]),
            candidate_top=raw["candidate_top"],
            reference_module=raw["reference_module"],
            testbench_top=raw["testbench_top"],
            pass_marker=raw["pass_marker"],
            fail_marker=raw["fail_marker"],
            synthesis_top=raw["synthesis_top"],
            clocks=clocks,
            power_base_clock=raw["power_base_clock"],
            file_hashes=tuple((name, digest) for name, digest in raw["file_hashes"]),
            testbench_projection=raw.get("testbench_projection", "identity-v1"),
            testbench_projection_sha256=raw.get("testbench_projection_sha256"),
        )
        if manifest.name in TASK_MANIFESTS or manifest.name in manifests:
            raise RuntimeError(f"duplicate RTLLM task manifest: {manifest.name}")
        if manifest.root not in FROZEN_TASK_TREES:
            raise RuntimeError(
                f"RTLLM task manifest is outside the frozen inventory: {manifest.root}"
            )
        manifests[manifest.name] = manifest
    return manifests


TASK_MANIFESTS.update(_load_additional_task_manifests())
ALL_TASK_NAMES = tuple(
    manifest.name for manifest in sorted(TASK_MANIFESTS.values(), key=lambda item: item.root)
)
_manifest_roots = {item.root for item in TASK_MANIFESTS.values()}
if len(TASK_MANIFESTS) != FROZEN_TASK_COUNT or _manifest_roots != set(FROZEN_TASK_TREES):
    raise RuntimeError("RTLLM runnable task manifests do not cover the frozen 50-task inventory")


__all__ = [
    "ADDITIONAL_TASK_CATALOG_SHA256",
    "ClockConstraint",
    "ALL_TASK_NAMES",
    "FROZEN_DATASET_FILES_HASH",
    "FROZEN_FILE_COUNT",
    "FROZEN_TASK_COUNT",
    "FROZEN_TASK_TREES",
    "FROZEN_TASK_TREES_HASH",
    "HARDER_TASK_NAMES",
    "RTLLMTaskManifest",
    "TASK_MANIFESTS",
]
