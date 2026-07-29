"""The shared multi-turn task environment used by the reference orchestrator."""

from __future__ import annotations

import time
from typing import Any

from verigym.core.artifact_policy import bound_value
from verigym.core.episode import BudgetTracker, EpisodeState, TerminationReason
from verigym.core.errors import PathPolicyError
from verigym.core.trace import TraceWriter
from verigym.core.workspace import WorkspacePolicy
from verigym.registry.base import PluginRegistry
from verigym.runtimes.base import Runtime, RuntimeSession
from verigym.schemas.agent import (
    AbortAction,
    AgentAction,
    ApplyPatchAction,
    FinalSubmissionAction,
    MessageAction,
    Observation,
    ToolCallAction,
)
from verigym.schemas.common import ErrorCategory, InteractionMode, ToolVisibility
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.task import ResolvedTaskAssets, VeriTask
from verigym.schemas.tool import ToolResult
from verigym.tools.base import ToolContext, ToolPlugin


class VeriGymEnv:
    """Policy-enforced reset/step environment with a persistent visible trace."""

    def __init__(
        self,
        *,
        task: VeriTask,
        assets: ResolvedTaskAssets,
        runtime: Runtime,
        tools: PluginRegistry[ToolPlugin],
        mode: InteractionMode = InteractionMode.AGENT,
    ) -> None:
        self.task = task
        self.assets = assets
        self.runtime = runtime
        self.tools = tools
        self.mode = mode
        self.state = EpisodeState.CREATED
        self.termination_reason: TerminationReason | None = None
        self.session: RuntimeSession | None = None
        self.tracker: BudgetTracker | None = None
        self.trace: TraceWriter | None = None
        self.run_id: str | None = None
        self.policy = WorkspacePolicy(
            editable_globs=tuple(task.workspace.editable_globs),
            readonly_globs=tuple(task.workspace.readonly_globs),
            excluded_globs=tuple(task.workspace.excluded_globs),
            max_changed_files=task.workspace.max_changed_files,
            max_patch_lines=task.workspace.max_patch_lines,
            max_workspace_bytes=task.budget.max_workspace_bytes,
        )

    def reset(self, *, run_id: str, trace: TraceWriter) -> tuple[Observation, dict[str, Any]]:
        if self.state != EpisodeState.CREATED:
            raise RuntimeError("an environment instance can only be reset once")
        self.run_id = run_id
        self.trace = trace
        self.state = EpisodeState.MATERIALIZING
        self.session = self.runtime.create_session(
            SessionSpec(
                source_dir=self.assets.visible_root,
                label="agent",
                max_output_bytes=self.task.budget.max_output_bytes_per_tool,
                read_only_mounts=self.assets.read_only_mounts,
            )
        )
        self.tracker = BudgetTracker(self.task.budget)
        self.state = EpisodeState.READY
        trace.emit(
            "episode_started",
            {
                "task_id": self.task.id,
                "state": self.state.value,
                "runtime": self.runtime.descriptor.name,
                "isolation_level": self.runtime.descriptor.isolation_level,
                "interaction_mode": self.mode.value,
            },
        )
        self.state = EpisodeState.RUNNING
        observation = self._observation(initial=True)
        trace.emit("observation_emitted", observation.model_dump(mode="json"))
        return observation, {"run_id": run_id, "state": self.state.value}

    def step(self, action: AgentAction) -> tuple[Observation, float, bool, bool, dict[str, Any]]:
        if self.state != EpisodeState.RUNNING or self.tracker is None or self.trace is None:
            raise RuntimeError(f"cannot step environment in state {self.state.value}")
        exhausted = self.tracker.exhausted_before_turn()
        if exhausted is not None:
            return self._truncate(exhausted)
        self.tracker.consume_turn()
        action_payload, action_truncated = bound_value(
            action.model_dump(mode="json"), self.task.budget.max_output_bytes_per_tool
        )
        assert isinstance(action_payload, dict)
        action_payload["content_truncated"] = action_truncated
        self.trace.emit("agent_action", action_payload)

        if isinstance(action, FinalSubmissionAction):
            if action.files is not None:
                submission_error = self._materialize_final_submission(action.files)
                if submission_error is not None:
                    self.trace.emit(
                        "agent_action_rejected",
                        {
                            "category": "submission_policy",
                            "message": submission_error,
                        },
                    )
                    self.state = EpisodeState.VERIFYING
                    self.termination_reason = TerminationReason.POLICY_VIOLATION
                    observation = self._observation(message=submission_error)
                    self._emit_budget()
                    return observation, 0.0, True, False, self._info()
            self.trace.emit(
                "final_submission",
                {
                    "message": action.message,
                    "paths": sorted(action.files) if action.files else [],
                },
            )
            self.state = EpisodeState.VERIFYING
            self.termination_reason = TerminationReason.FINAL_SUBMISSION
            observation = self._observation(message=action.message)
            self._emit_budget()
            return observation, 0.0, True, False, self._info()
        if isinstance(action, AbortAction):
            self.state = EpisodeState.FAILED
            self.termination_reason = TerminationReason.AGENT_ABORT
            observation = self._observation(message=action.reason)
            self._emit_budget()
            return observation, 0.0, True, False, self._info()
        if isinstance(action, MessageAction):
            observation = self._observation(message=action.message)
            self._emit_budget()
            self.trace.emit("observation_emitted", observation.model_dump(mode="json"))
            return observation, 0.0, False, False, self._info()

        if isinstance(action, ApplyPatchAction):
            tool_name = "file.apply_patch"
            arguments = {"patch": action.patch}
        elif isinstance(action, ToolCallAction):
            tool_name = action.tool
            arguments = action.arguments
        else:  # pragma: no cover - the discriminated union prevents this at API boundaries.
            self.state = EpisodeState.FAILED
            self.termination_reason = TerminationReason.POLICY_VIOLATION
            observation = self._observation(message="unsupported action type")
            return observation, 0.0, True, False, self._info()

        if self.mode == InteractionMode.CHAT:
            result = ToolResult(
                tool=tool_name,
                success=False,
                category=ErrorCategory.POLICY_DENIED,
                message="ChatEval does not permit tool access",
                stderr="ChatEval does not permit tool access",
            )
            self.tracker.failed_tool_calls += 1
            self.trace.emit(
                "agent_action_rejected",
                {
                    "category": "chat_tool_policy",
                    "message": result.message,
                    "tool": tool_name,
                },
            )
            self.trace.emit("tool_result", result.model_dump(mode="json"))
            self._emit_budget()
            observation = self._observation(previous_tool_result=result)
            self.trace.emit("observation_emitted", observation.model_dump(mode="json"))
            return observation, 0.0, False, False, self._info()

        exhausted = self.tracker.exhausted_before_tool()
        if exhausted is not None:
            return self._truncate(exhausted)
        arguments = self._bounded_tool_arguments(tool_name, arguments)
        self.tracker.consume_tool()
        trace_arguments, arguments_truncated = bound_value(
            arguments, self.task.budget.max_output_bytes_per_tool
        )
        request_event = self.trace.emit(
            "tool_request",
            {
                "tool": tool_name,
                "arguments": trace_arguments,
                "arguments_truncated": arguments_truncated,
            },
        )
        started = time.monotonic()
        result = self._execute_tool(tool_name, arguments)
        elapsed = time.monotonic() - started
        self.tracker.tool_time_s += elapsed
        if not result.success:
            self.tracker.failed_tool_calls += 1
        if result.category == ErrorCategory.POLICY_DENIED:
            self.trace.emit(
                "agent_action_rejected",
                {
                    "category": "tool_policy",
                    "message": result.message,
                    "tool": tool_name,
                },
                parent_event_id=request_event.event_id,
            )
        result_event = self.trace.emit(
            "tool_result",
            result.model_dump(mode="json"),
            parent_event_id=request_event.event_id,
        )
        changed_files = (
            result.metadata.get("changed_files", [])
            if tool_name in {"file.apply_patch", "file.write"}
            else []
        )
        if tool_name == "file.apply_patch" and result.success:
            self.trace.emit(
                "patch_applied",
                {"paths": changed_files},
                parent_event_id=result_event.event_id,
            )
        if changed_files:
            self.trace.emit("file_changed", {"paths": changed_files, "tool": tool_name})
        self._emit_budget()
        observation = self._observation(previous_tool_result=result)
        self.trace.emit("observation_emitted", observation.model_dump(mode="json"))
        return observation, 0.0, False, False, self._info()

    def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        if self.tracker is None or self.session is None:
            raise RuntimeError("environment has no active session")
        if (
            tool_name not in self.task.interaction.allowed_tools
            or tool_name in self.task.interaction.denied_tools
        ):
            return ToolResult(
                tool=tool_name,
                success=False,
                category=ErrorCategory.POLICY_DENIED,
                message="tool is not allowed by this task",
                stderr="tool is not allowed by this task",
            )
        try:
            plugin = self.tools.get(tool_name)
        except Exception as exc:
            return ToolResult(
                tool=tool_name,
                success=False,
                category=ErrorCategory.TOOL_NOT_FOUND,
                message=str(exc),
                stderr=str(exc),
            )
        if plugin.descriptor.visibility == ToolVisibility.VERIFIER_ONLY:
            return ToolResult(
                tool=tool_name,
                success=False,
                category=ErrorCategory.POLICY_DENIED,
                message="verifier-only tool is not agent-visible",
                stderr="verifier-only tool is not agent-visible",
            )
        return plugin.execute(
            arguments,
            ToolContext(
                session=self.session,
                workspace_policy=self.policy,
                max_output_bytes=self.task.budget.max_output_bytes_per_tool,
            ),
        )

    def _bounded_tool_arguments(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        bounded = dict(arguments)
        limit = self.task.budget.max_tool_time_s
        if limit is not None and tool_name.startswith("iverilog."):
            requested = bounded.get("timeout_s")
            if requested is None or (isinstance(requested, int) and requested > limit):
                bounded["timeout_s"] = limit
        return bounded

    def _materialize_final_submission(self, files: dict[str, str]) -> str | None:
        if self.session is None or self.trace is None:
            return "environment has no active workspace"
        if self.mode != InteractionMode.CHAT:
            return "direct file submission is only permitted in ChatEval"
        expected = set(self.task.workspace.entrypoints)
        if not expected or set(files) != expected:
            return f"submission paths must exactly match entrypoints: {sorted(expected)}"
        previous: dict[str, bytes | None] = {}
        try:
            for raw_path, content in files.items():
                relative = self.policy.check_write(raw_path)
                target = self.session.root / relative
                previous[relative] = target.read_bytes() if target.is_file() else None
                self.session.write_file(relative, content.encode("utf-8"))
            diff = self.session.snapshot_diff()
            self.policy.check_patch_size(
                len(diff.changed_files), diff.added_lines + diff.deleted_lines
            )
            if self.task.budget.max_workspace_bytes is not None:
                size = 0
                for path in self.session.root.rglob("*"):
                    if path.is_symlink():
                        raise PathPolicyError("symlinks are not permitted inside the workspace")
                    if path.is_file() and ".verigym_internal" not in path.parts:
                        size += path.stat().st_size
                if size > self.task.budget.max_workspace_bytes:
                    raise PathPolicyError(
                        f"workspace uses {size} bytes; limit is "
                        f"{self.task.budget.max_workspace_bytes}"
                    )
        except Exception as exc:
            for relative, prior_content in previous.items():
                target = self.session.root / relative
                if prior_content is None:
                    target.unlink(missing_ok=True)
                else:
                    self.session.write_file(relative, prior_content)
            return str(exc)
        self.trace.emit(
            "file_changed",
            {"paths": sorted(files), "source": "final_submission"},
        )
        return None

    def _truncate(
        self, reason: TerminationReason
    ) -> tuple[Observation, float, bool, bool, dict[str, Any]]:
        self.state = EpisodeState.VERIFYING
        self.termination_reason = reason
        observation = self._observation(message=reason.value)
        self._emit_budget()
        return observation, 0.0, False, True, self._info()

    def terminate(self, reason: TerminationReason, message: str) -> Observation:
        """Terminate before an action when the harness or model boundary fails."""

        if self.state != EpisodeState.RUNNING:
            raise RuntimeError(f"cannot terminate environment in state {self.state.value}")
        self.state = EpisodeState.VERIFYING
        self.termination_reason = reason
        observation = self._observation(message=message)
        self._emit_budget()
        return observation

    def _visible_files(self) -> list[str]:
        assert self.session is not None
        files: list[str] = []
        for path in sorted(self.session.root.rglob("*")):
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            relative = path.relative_to(self.session.root).as_posix()
            if not self.policy.is_excluded(relative):
                files.append(relative)
        return files

    def _observation(
        self,
        *,
        initial: bool = False,
        previous_tool_result: ToolResult | None = None,
        message: str | None = None,
    ) -> Observation:
        if self.tracker is None or self.session is None:
            raise RuntimeError("environment has not been reset")
        selected: dict[str, str] = {}
        if initial and self.task.interaction.initial_observation.include_readme:
            try:
                selected["README.md"] = self.session.read_file("README.md").decode("utf-8")
            except FileNotFoundError:
                pass
        diff = self.session.snapshot_diff()
        return Observation(
            task_id=self.task.id,
            task_description=self.task.description if initial else None,
            visible_files=(
                self._visible_files()
                if initial and self.task.interaction.initial_observation.include_tree
                else []
            ),
            selected_files=selected,
            previous_tool_result=previous_tool_result,
            remaining_budget=self.tracker.remaining(),
            diff_summary={
                "changed_files": diff.changed_files,
                "added_lines": diff.added_lines,
                "deleted_lines": diff.deleted_lines,
            },
            policy_reminders=(
                [
                    "ChatEval permits final submission only and exposes no tools.",
                    "Hidden verifier assets are not present in this workspace.",
                    f"Editable globs: {', '.join(self.task.workspace.editable_globs)}",
                ]
                if self.mode == InteractionMode.CHAT
                else [
                    "Only task-allowed tools may be used.",
                    "Hidden verifier assets are not present in this workspace.",
                    f"Editable globs: {', '.join(self.task.workspace.editable_globs)}",
                ]
            ),
            episode_status=self.state.value,
            message=message,
        )

    def _emit_budget(self) -> None:
        assert self.trace is not None and self.tracker is not None
        self.trace.emit(
            "budget_updated",
            {
                "consumed": {
                    "turns": self.tracker.turns,
                    "tool_calls": self.tracker.tool_calls,
                    "model_calls": self.tracker.model_calls,
                    "model_input_tokens": self.tracker.model_input_tokens,
                    "model_output_tokens": self.tracker.model_output_tokens,
                    "total_tokens": self.tracker.total_tokens,
                    "wall_time_s": self.tracker.wall_time_s,
                },
                "remaining": self.tracker.remaining().model_dump(mode="json"),
            },
        )

    def _info(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "termination_reason": (
                self.termination_reason.value if self.termination_reason else None
            ),
        }

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
