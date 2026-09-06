"""Topological verifier execution with normalized gate and skip semantics."""

from __future__ import annotations

import json
import time
from graphlib import TopologicalSorter
from pathlib import Path

from verigym.core.errors import PluginNotFoundError
from verigym.registry.base import PluginRegistry
from verigym.runtimes.base import RuntimeSession
from verigym.schemas.base import SCHEMA_VERSION
from verigym.schemas.common import ErrorCategory, ToolVisibility
from verigym.schemas.tool import ToolResult
from verigym.schemas.verifier import (
    VerifierGraph,
    VerifierNode,
    VerifierResult,
    VerifierStatus,
)
from verigym.schemas.verifier_profile import ResolvedVerifierToolProfile, VerifierToolProfile
from verigym.tools.base import ToolContext, ToolPlugin

_INFRASTRUCTURE_CATEGORIES = {
    ErrorCategory.TIMEOUT,
    ErrorCategory.OUT_OF_MEMORY,
    ErrorCategory.OUTPUT_LIMIT,
    ErrorCategory.INVALID_REQUEST,
    ErrorCategory.TOOL_NOT_FOUND,
    ErrorCategory.LICENSE_UNAVAILABLE,
    ErrorCategory.UNSUPPORTED_VERSION,
    ErrorCategory.PARSER_ERROR,
    ErrorCategory.SANDBOX_ERROR,
    ErrorCategory.PERMISSION_DENIED,
    ErrorCategory.POLICY_DENIED,
    ErrorCategory.INTERNAL_ERROR,
}


class VerifierExecutor:
    """Run a validated verifier DAG in one verifier-only runtime session."""

    def __init__(self, tools: PluginRegistry[ToolPlugin]) -> None:
        self._tools = tools

    def execute(
        self,
        graph: VerifierGraph,
        session: RuntimeSession,
        artifact_root: Path,
        *,
        max_output_bytes: int,
        verifier_profile: VerifierToolProfile | None = None,
        resolved_verifier_profile: ResolvedVerifierToolProfile | None = None,
    ) -> list[VerifierResult]:
        artifact_root.mkdir(parents=True, exist_ok=True)
        nodes = {node.id: node for node in graph.nodes}
        order = tuple(
            TopologicalSorter(
                {node.id: set(node.depends_on) for node in graph.nodes}
            ).static_order()
        )
        results: dict[str, VerifierResult] = {}
        tool_results: dict[str, ToolResult] = {}
        for node_id in order:
            node = nodes[node_id]
            if not self._should_run(node, results):
                result = VerifierResult(
                    node_id=node.id,
                    plugin=node.plugin,
                    status=VerifierStatus.SKIPPED,
                    error_category=ErrorCategory.SUCCESS,
                    message="dependency did not pass",
                    request=node.request,
                )
                results[node.id] = result
                self._persist(node, result, None, artifact_root, session)
                continue
            request = dict(node.request)
            if node.timeout_s is not None:
                request["timeout_s"] = node.timeout_s
            executable_from = request.get("executable_from")
            if executable_from:
                dependency = tool_results.get(str(executable_from))
                if dependency is None or "executable" not in dependency.metadata:
                    result = VerifierResult(
                        node_id=node.id,
                        plugin=node.plugin,
                        status=VerifierStatus.ERROR,
                        error_category=ErrorCategory.INVALID_REQUEST,
                        message=f"dependency {executable_from!r} supplied no executable artifact",
                        request=request,
                    )
                    results[node.id] = result
                    self._persist(node, result, None, artifact_root, session)
                    continue
                request["executable"] = dependency.metadata["executable"]
            started = time.monotonic()
            try:
                plugin = self._tools.get(node.plugin)
                if plugin.descriptor.visibility == ToolVisibility.AGENT_VISIBLE:
                    raise ValueError(f"agent-only plugin cannot run in verifier DAG: {node.plugin}")
                tool_result = plugin.execute(
                    request,
                    ToolContext(
                        session=session,
                        max_output_bytes=max_output_bytes,
                        artifact_dir=artifact_root / node.id,
                        verifier_profile=verifier_profile,
                        resolved_verifier_profile=resolved_verifier_profile,
                    ),
                )
                tool_results[node.id] = tool_result
                candidate_failure = tool_result.metadata.get("candidate_failure") is True
                status = (
                    VerifierStatus.PASSED
                    if tool_result.success
                    else VerifierStatus.FAILED
                    if candidate_failure
                    else VerifierStatus.ERROR
                    if tool_result.category in _INFRASTRUCTURE_CATEGORIES
                    else VerifierStatus.FAILED
                )
                result = VerifierResult(
                    node_id=node.id,
                    plugin=node.plugin,
                    status=status,
                    error_category=tool_result.category,
                    message=tool_result.message,
                    request=request,
                    duration_s=time.monotonic() - started,
                    exit_code=tool_result.exit_code,
                    tests_passed=tool_result.metadata.get("tests_passed"),
                    tests_total=tool_result.metadata.get("tests_total"),
                    diagnostics=tool_result.diagnostics,
                    metadata=tool_result.metadata,
                )
            except PluginNotFoundError as exc:
                tool_result = None
                result = VerifierResult(
                    node_id=node.id,
                    plugin=node.plugin,
                    status=VerifierStatus.ERROR,
                    error_category=ErrorCategory.TOOL_NOT_FOUND,
                    message=str(exc),
                    request=request,
                    duration_s=time.monotonic() - started,
                )
            except Exception as exc:
                tool_result = None
                result = VerifierResult(
                    node_id=node.id,
                    plugin=node.plugin,
                    status=VerifierStatus.ERROR,
                    error_category=ErrorCategory.INTERNAL_ERROR,
                    message=str(exc),
                    request=request,
                    duration_s=time.monotonic() - started,
                )
            results[node.id] = result
            result.artifacts = self._persist(node, result, tool_result, artifact_root, session)
        return [results[node_id] for node_id in order]

    @staticmethod
    def _should_run(node: VerifierNode, results: dict[str, VerifierResult]) -> bool:
        if not node.depends_on:
            return True
        if node.run_if is not None and node.run_if.kind == "always":
            return True
        if node.run_if is not None and node.run_if.kind == "dependency_failed":
            selected = node.run_if.node or node.depends_on[0]
            return selected in results and results[selected].status == VerifierStatus.FAILED
        return all(
            dependency in results and results[dependency].status == VerifierStatus.PASSED
            for dependency in node.depends_on
        )

    @staticmethod
    def _persist(
        node: VerifierNode,
        result: VerifierResult,
        tool_result: ToolResult | None,
        artifact_root: Path,
        session: RuntimeSession,
    ) -> list[str]:
        node_dir = artifact_root / node.id
        node_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[str] = []
        persisted_request = {"schema_version": SCHEMA_VERSION, **result.request}
        (node_dir / "request.json").write_text(
            json.dumps(persisted_request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifacts.append((Path(node.id) / "request.json").as_posix())
        if tool_result is not None:
            (node_dir / "stdout.log").write_text(tool_result.stdout, encoding="utf-8")
            (node_dir / "stderr.log").write_text(tool_result.stderr, encoding="utf-8")
            (node_dir / "tool_result.json").write_text(
                tool_result.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            artifacts.extend(
                [
                    (Path(node.id) / "stdout.log").as_posix(),
                    (Path(node.id) / "stderr.log").as_posix(),
                    (Path(node.id) / "tool_result.json").as_posix(),
                ]
            )
            if tool_result.success and "executable" in tool_result.metadata:
                source = tool_result.metadata["executable"]
                if isinstance(source, str):
                    source_path = (session.root / source).resolve(strict=False)
                    if source_path.is_file() and source_path.is_relative_to(session.root):
                        destination = node_dir / "executable"
                        destination.write_bytes(source_path.read_bytes())
                        artifacts.append((Path(node.id) / "executable").as_posix())
        verifier_result_path = (Path(node.id) / "verifier_result.json").as_posix()
        artifacts.append(verifier_result_path)
        result.artifacts = list(artifacts)
        (node_dir / "verifier_result.json").write_text(
            result.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return artifacts


def has_infrastructure_error(results: list[VerifierResult]) -> bool:
    return any(result.status == VerifierStatus.ERROR for result in results)
