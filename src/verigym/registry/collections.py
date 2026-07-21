"""Registry collection and built-in plugin assembly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from verigym.registry.base import PluginRegistry


@dataclass
class Registries:
    suites: PluginRegistry[Any]
    tools: PluginRegistry[Any]
    agents: PluginRegistry[Any]
    models: PluginRegistry[Any]
    runtimes: PluginRegistry[Any]

    def discover_external(self) -> None:
        for registry in (self.suites, self.tools, self.agents, self.models, self.runtimes):
            registry.discover()


def build_registries(*, discover_external: bool = True) -> Registries:
    """Create a fresh registry collection populated with first-party plugins."""

    from verigym.agents.react import ReferenceReActAgent
    from verigym.agents.scripted import ScriptedAgent, ScriptedBadAgent
    from verigym.agents.single_turn import SingleTurnAgent
    from verigym.models.static import builtin_model_clients
    from verigym.runtimes.local import LocalRuntime
    from verigym.suites.toy_rtl.adapter import ToyRtlSuite
    from verigym.suites.verilog_eval.adapter import VerilogEvalSuite
    from verigym.suites.verilog_eval.verifier import builtin_verilog_eval_tools
    from verigym.tools.file_tools import builtin_file_tools
    from verigym.tools.iverilog import builtin_iverilog_tools

    registries = Registries(
        suites=PluginRegistry("verigym.suites"),
        tools=PluginRegistry("verigym.tools"),
        agents=PluginRegistry("verigym.agents"),
        models=PluginRegistry("verigym.models"),
        runtimes=PluginRegistry("verigym.runtimes"),
    )
    registries.suites.register(ToyRtlSuite())
    registries.suites.register(VerilogEvalSuite())
    for tool in [
        *builtin_file_tools(),
        *builtin_iverilog_tools(),
        *builtin_verilog_eval_tools(),
    ]:
        registries.tools.register(tool)
    registries.agents.register(ScriptedAgent())
    registries.agents.register(ScriptedBadAgent())
    registries.agents.register(SingleTurnAgent())
    registries.agents.register(ReferenceReActAgent())
    for model in builtin_model_clients():
        registries.models.register(model)
    registries.runtimes.register(LocalRuntime())
    if discover_external:
        registries.discover_external()
    return registries
