"""Registry collection and built-in plugin assembly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from verigym.profiles.registry import ToolchainProfileRegistry, builtin_profiles
from verigym.registry.base import PluginDiagnostic, PluginOrigin, PluginRegistry
from verigym.version import __version__


@dataclass
class Registries:
    suites: PluginRegistry[Any]
    tools: PluginRegistry[Any]
    agents: PluginRegistry[Any]
    models: PluginRegistry[Any]
    runtimes: PluginRegistry[Any]
    profiles: ToolchainProfileRegistry

    def discover_external(self) -> None:
        for registry in (self.suites, self.tools, self.agents, self.models, self.runtimes):
            registry.discover()

    def diagnostics(self) -> list[PluginDiagnostic]:
        return [
            diagnostic
            for registry in (self.suites, self.tools, self.agents, self.models, self.runtimes)
            for diagnostic in registry.diagnostics()
        ]


def build_registries(*, discover_external: bool = True) -> Registries:
    """Create a fresh registry collection populated with first-party plugins."""

    from verigym.agents.api_repository import ApiRepositoryAgent
    from verigym.agents.api_repository_v2 import ProviderNeutralApiRepositoryAgent
    from verigym.agents.react import ReferenceReActAgent, VersionedContextReActAgent
    from verigym.agents.repository_scripted import (
        ScriptedRepositoryBadAgent,
        ScriptedRepositoryGoodAgent,
        ScriptedRepositoryPolicyBadAgent,
    )
    from verigym.agents.scripted import ScriptedAgent, ScriptedBadAgent
    from verigym.agents.single_turn import SingleTurnAgent
    from verigym.models.static import builtin_model_clients
    from verigym.runtimes.docker import DockerRuntime
    from verigym.runtimes.local import LocalRuntime
    from verigym.suites.repo_api_protocol.adapter import RepositoryApiProtocolSuite
    from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite
    from verigym.suites.toy_rtl.adapter import ToyRtlSuite
    from verigym.suites.verilog_eval.adapter import VerilogEvalSuite
    from verigym.suites.verilog_eval.verifier import builtin_verilog_eval_tools
    from verigym.tools.file_tools import builtin_file_tools
    from verigym.tools.iverilog import builtin_iverilog_tools
    from verigym.tools.repository import builtin_repository_tools
    from verigym.tools.yosys import builtin_yosys_tools

    registries = Registries(
        suites=PluginRegistry("verigym.suites"),
        tools=PluginRegistry("verigym.tools"),
        agents=PluginRegistry("verigym.agents"),
        models=PluginRegistry("verigym.models"),
        runtimes=PluginRegistry("verigym.runtimes"),
        profiles=builtin_profiles(),
    )
    builtin_origin = PluginOrigin(
        package="verigym",
        version=__version__,
        entry_point=None,
        registration="builtin",
    )
    registries.suites.register(ToyRtlSuite(), origin=builtin_origin)
    registries.suites.register(RepositoryRtlSuite(), origin=builtin_origin)
    registries.suites.register(RepositoryApiProtocolSuite(), origin=builtin_origin)
    registries.suites.register(VerilogEvalSuite(), origin=builtin_origin)
    for tool in [
        *builtin_file_tools(),
        *builtin_iverilog_tools(),
        *builtin_repository_tools(),
        *builtin_verilog_eval_tools(),
        *builtin_yosys_tools(),
    ]:
        registries.tools.register(tool, origin=builtin_origin)
    registries.agents.register(ScriptedAgent(), origin=builtin_origin)
    registries.agents.register(ScriptedBadAgent(), origin=builtin_origin)
    registries.agents.register(SingleTurnAgent(), origin=builtin_origin)
    registries.agents.register(ReferenceReActAgent(), origin=builtin_origin)
    registries.agents.register(VersionedContextReActAgent(), origin=builtin_origin)
    registries.agents.register(ApiRepositoryAgent(), origin=builtin_origin)
    registries.agents.register(ProviderNeutralApiRepositoryAgent(), origin=builtin_origin)
    registries.agents.register(ScriptedRepositoryGoodAgent(), origin=builtin_origin)
    registries.agents.register(ScriptedRepositoryBadAgent(), origin=builtin_origin)
    registries.agents.register(ScriptedRepositoryPolicyBadAgent(), origin=builtin_origin)
    for model in builtin_model_clients():
        registries.models.register(model, origin=builtin_origin)
    registries.runtimes.register(LocalRuntime(), origin=builtin_origin)
    registries.runtimes.register(DockerRuntime(), origin=builtin_origin)
    if discover_external:
        registries.discover_external()
    return registries
