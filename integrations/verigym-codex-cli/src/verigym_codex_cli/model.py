"""Track A: CLI-mediated, single-turn, zero-tool-use ModelClient."""

from __future__ import annotations

import html
import tempfile
from pathlib import Path
from typing import Any, cast

from verigym.plugin_api import (
    PLUGIN_API_VERSION,
    SCHEMA_VERSION,
    JsonValue,
    ModelClient,
    ModelClientError,
    ModelClientErrorInfo,
    ModelDescriptor,
    ModelErrorCategory,
    ModelFinishReason,
    ModelRequest,
    ModelResponse,
    ModelRunConfig,
    NormalizedModelUsage,
)

from ._version import __version__
from .artifacts import CodexRunEvidence
from .capabilities import CapabilityReport, runtime_capabilities
from .config import CodexSettings, model_settings
from .events import EventParseError, ParsedEventStream, parse_event_stream
from .invocation import build_exec_arguments, sanitized_invocation
from .process import (
    CodexCliProcessRunner,
    CodexProcessError,
    CodexProcessResult,
    ExecutableIdentity,
)
from .security import assert_empty_directory, assert_instruction_isolation
from .util import redact_text, stable_hash


class CodexExecModelClient(ModelClient):
    """One Codex exec process per request; any observed tool use invalidates it."""

    def __init__(
        self,
        *,
        executable: ExecutableIdentity | None = None,
        capabilities: CapabilityReport | None = None,
        settings: CodexSettings | None = None,
        sample_index: int | None = None,
    ) -> None:
        self._executable = executable
        self._capabilities = capabilities
        self._settings = settings
        self._sample_index = sample_index
        self._called = False
        self._events: list[tuple[str, dict[str, JsonValue]]] = []
        self._evidence: CodexRunEvidence | None = None
        self._last_parsed: ParsedEventStream | None = None
        safe_configuration: dict[str, Any] = {
            "integration_track": "codex_cli_model_proxy",
            "pure_api_model_eval": False,
            "direct_api_benchmark": False,
            "configured": settings is not None,
        }
        model_id = "unconfigured"
        fingerprint = stable_hash(safe_configuration)
        if settings is not None and capabilities is not None:
            model_id = settings.model_id
            safe_configuration = settings.safe_configuration(capabilities)
            safe_configuration["sample_index"] = sample_index
            fingerprint = stable_hash(safe_configuration)
        self.descriptor = ModelDescriptor(
            schema_version=SCHEMA_VERSION,
            name="codex-cli-exec-model",
            version=__version__,
            api_version=PLUGIN_API_VERSION,
            provider="openai-codex-cli",
            capabilities=[
                "text",
                "cli_mediated_single_turn",
                "machine_readable_events",
                "optional_network",
            ],
            api_compatibility="codex.exec.machine-readable",
            model_id=model_id,
            client_name="codex-cli-exec",
            client_version=__version__,
            configuration_fingerprint=fingerprint,
            configuration=safe_configuration,
        )

    def clone_for_run(
        self,
        configuration: ModelRunConfig | None = None,
    ) -> CodexExecModelClient:
        config = configuration or ModelRunConfig()
        executable, capabilities = runtime_capabilities()
        settings = model_settings(config, capabilities)
        return CodexExecModelClient(
            executable=executable,
            capabilities=capabilities,
            settings=settings,
            sample_index=config.sample_index,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._called:
            raise self._error(
                ModelErrorCategory.CONFIGURATION,
                "Codex CLI model-proxy clones permit exactly one request",
            )
        self._called = True
        executable, capabilities, settings = self._configured()
        envelope = _serialize_request(request)
        arguments = build_exec_arguments(capabilities, settings)
        invocation = sanitized_invocation(
            arguments,
            settings,
            capabilities,
            working_directory_policy="new_empty_temporary_directory",
        )
        self._events = [
            (
                "codex_cli_capabilities_resolved",
                {
                    "capability_fingerprint": capabilities.capability_fingerprint,
                    "executable_sha256": capabilities.executable_sha256,
                    "model_call_count": 0,
                },
            ),
            (
                "codex_cli_process_started",
                {
                    "integration_track": settings.integration_track,
                    "sandbox_policy": settings.sandbox_policy,
                    "working_directory_policy": "empty",
                },
            ),
        ]
        parsed: ParsedEventStream | None = None
        self._last_parsed = None
        failure: ModelClientError | None = None
        response: ModelResponse | None = None
        with tempfile.TemporaryDirectory(prefix="verigym-codex-model-") as temporary:
            workspace = Path(temporary).resolve()
            try:
                assert_instruction_isolation(workspace)
                assert_empty_directory(workspace)
            except Exception as exc:
                raise self._error(
                    ModelErrorCategory.CONFIGURATION,
                    str(exc),
                ) from exc
            runner = CodexCliProcessRunner(
                executable,
                auth_mode=settings.resolved_auth_mode,
                credential_env=settings.credential_env,
                max_output_bytes=settings.max_output_bytes,
                allow_proxy_environment=settings.allow_proxy_environment,
            )
            try:
                process = runner.run(
                    arguments,
                    cwd=workspace,
                    timeout_s=settings.max_process_time_s,
                    stdin_bytes=envelope.encode("utf-8"),
                )
            except CodexProcessError as exc:
                process = _failed_process(str(exc))
                failure = self._error(
                    ModelErrorCategory.CONFIGURATION,
                    str(exc),
                )
            if failure is None:
                try:
                    parsed = self._validate_process(process, workspace)
                    response = ModelResponse(
                        request_id=request.request_id,
                        response_id=parsed.session_id,
                        provider_model_id=parsed.observed_model_id,
                        system_fingerprint=parsed.system_fingerprint,
                        text=parsed.final_messages[0],
                        finish_reason=ModelFinishReason.STOP,
                        usage=NormalizedModelUsage(
                            input_tokens=parsed.input_tokens,
                            output_tokens=parsed.output_tokens,
                            total_tokens=parsed.total_tokens,
                        ),
                        latency_s=process.duration_s,
                    )
                except ModelClientError as exc:
                    failure = exc
                    parsed = self._last_parsed
                except EventParseError as exc:
                    failure = self._error(
                        ModelErrorCategory.INVALID_RESPONSE,
                        str(exc),
                    )
                    parsed = self._last_parsed
            if any(workspace.iterdir()):
                failure = self._error(
                    ModelErrorCategory.INVALID_RESPONSE,
                    "Track A Codex process modified its empty working directory",
                )
            identity = self._identity(parsed, settings, capabilities)
            accounting = _accounting(process, parsed)
            self._evidence = CodexRunEvidence(
                capabilities=capabilities,
                invocation=invocation,
                process=process,
                parsed=parsed,
                identity=identity,
                accounting=accounting,
                summary={
                    "integration_track": settings.integration_track,
                    "valid_model_response": failure is None,
                    "tool_use_event_count": (
                        len(parsed.tool_use_events) if parsed is not None else None
                    ),
                    "final_message_count": (
                        len(parsed.final_messages) if parsed is not None else None
                    ),
                    "failure_category": (
                        failure.info.category.value if failure is not None else None
                    ),
                    "failure_message": (failure.info.message if failure is not None else None),
                },
                roots_to_redact=(workspace,),
            )
        self._events.append(
            (
                "codex_cli_process_completed",
                {
                    "exit_code": process.exit_code,
                    "timed_out": process.timed_out,
                    "event_count": len(parsed.events) if parsed is not None else 0,
                },
            )
        )
        self._events.append(
            (
                "codex_cli_identity_observed",
                {
                    "requested_model_id": settings.model_id,
                    "observed_model_id": (parsed.observed_model_id if parsed is not None else None),
                    "capability_fingerprint": capabilities.capability_fingerprint,
                    "configuration_fingerprint": self.descriptor.configuration_fingerprint,
                },
            )
        )
        if failure is not None:
            raise failure
        assert response is not None
        return response

    def drain_events(self) -> list[tuple[str, dict[str, JsonValue]]]:
        events = self._events
        self._events = []
        return events

    def export_run_artifacts(self, destination: Path) -> None:
        if self._evidence is None:
            raise RuntimeError("Codex model-proxy evidence is unavailable")
        self._evidence.write(destination, create=True)

    def _validate_process(
        self,
        process: CodexProcessResult,
        workspace: Path,
    ) -> ParsedEventStream:
        if process.timed_out:
            raise self._error(ModelErrorCategory.TIMEOUT, "Codex CLI process timed out")
        if process.stdout_truncated or process.stderr_truncated:
            raise self._error(
                ModelErrorCategory.INVALID_RESPONSE,
                "Codex CLI output exceeded the configured bound",
            )
        parsed: ParsedEventStream | None = None
        if process.stdout.strip():
            parsed = parse_event_stream(process.stdout, roots=(workspace,))
            self._last_parsed = parsed
            for event in parsed.events:
                self._events.append(
                    (
                        "codex_cli_event_observed",
                        {
                            "sequence": event.sequence,
                            "category": event.category,
                            "upstream_type": event.upstream_type,
                        },
                    )
                )
        if process.exit_code != 0:
            category = _remote_category(process.stderr, parsed)
            raise self._error(
                category,
                _safe_remote_message(process.stderr, parsed),
                retryable=category in {ModelErrorCategory.RATE_LIMIT, ModelErrorCategory.TRANSPORT},
            )
        if parsed is None:
            raise EventParseError("Codex CLI emitted no machine-readable events")
        if parsed.error_messages:
            category = _remote_category(process.stderr, parsed)
            raise self._error(
                category,
                _safe_remote_message(process.stderr, parsed),
            )
        if not parsed.terminal_event_seen:
            raise EventParseError("Codex CLI stream has no required terminal event")
        if parsed.tool_use_events:
            self._events.append(
                (
                    "codex_cli_tool_use_detected",
                    {
                        "count": len(parsed.tool_use_events),
                        "categories": cast(
                            list[JsonValue],
                            sorted({event.category for event in parsed.tool_use_events}),
                        ),
                    },
                )
            )
            raise self._error(
                ModelErrorCategory.INVALID_RESPONSE,
                "Track A observed forbidden Codex CLI tool use",
            )
        if len(parsed.final_messages) != 1:
            raise EventParseError("Codex CLI must emit exactly one nonempty final response")
        return parsed

    def _identity(
        self,
        parsed: ParsedEventStream | None,
        settings: CodexSettings,
        capabilities: CapabilityReport,
    ) -> dict[str, Any]:
        observed = parsed.observed_model_id if parsed is not None else None
        return {
            "schema_version": "1.0",
            "adapter_name": "codex-cli-exec",
            "adapter_version": __version__,
            "integration_track": "codex_cli_model_proxy",
            "requested_model_id": settings.model_id,
            "observed_model_id": observed,
            "executable_name": capabilities.executable_name,
            "executable_sha256": capabilities.executable_sha256,
            "executable_version": capabilities.version_output,
            "capability_fingerprint": capabilities.capability_fingerprint,
            "configuration_fingerprint": self.descriptor.configuration_fingerprint,
            "invocation_count": 1,
            "identity_confidence": "observed" if observed else "requested_only",
            "reproducibility_scope": "mutable_remote_observation",
            "auth_mode_label": settings.auth_mode_label,
            "requested_auth_mode": settings.requested_auth_mode,
            "resolved_auth_mode": settings.resolved_auth_mode,
            "auth_semantic_id": settings.auth_semantic_id,
            "auth_alias_used": settings.auth_alias_used,
            "pure_api_model_eval": False,
        }

    def _configured(
        self,
    ) -> tuple[ExecutableIdentity, CapabilityReport, CodexSettings]:
        if self._executable is None or self._capabilities is None or self._settings is None:
            raise self._error(
                ModelErrorCategory.CONFIGURATION,
                "codex-cli-exec-model must be cloned with explicit configuration",
            )
        return self._executable, self._capabilities, self._settings

    @staticmethod
    def _error(
        category: ModelErrorCategory,
        message: str,
        *,
        retryable: bool = False,
    ) -> ModelClientError:
        return ModelClientError(
            ModelClientErrorInfo(
                category=category,
                message=redact_text(message)[:4096],
                retryable=retryable,
            )
        )


def _serialize_request(request: ModelRequest) -> str:
    lines = ['<verigym_model_request schema_version="1.0">']
    for message in request.messages:
        content = "".join(
            character if character in {"\n", "\t"} or ord(character) >= 32 else " "
            for character in message.content
        )
        escaped = html.escape(content, quote=False).replace(
            "&lt;/message&gt;",
            "&lt;\\/message&gt;",
        )
        lines.extend(
            [
                f'<message role="{message.role}">',
                escaped,
                "</message>",
            ]
        )
    lines.append("</verigym_model_request>")
    return "\n".join(lines) + "\n"


def _accounting(
    process: CodexProcessResult,
    parsed: ParsedEventStream | None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "process_wall_time_s": process.duration_s,
        "cli_event_count": len(parsed.events) if parsed is not None else 0,
        "external_tool_call_count": (parsed.external_tool_count if parsed is not None else None),
        "external_command_count": parsed.command_count if parsed is not None else None,
        "external_file_read_count": (parsed.file_read_count if parsed is not None else None),
        "external_file_write_count": (parsed.file_write_count if parsed is not None else None),
        "external_patch_count": parsed.patch_count if parsed is not None else None,
        "input_tokens": parsed.input_tokens if parsed is not None else None,
        "output_tokens": parsed.output_tokens if parsed is not None else None,
        "total_tokens": parsed.total_tokens if parsed is not None else None,
        "cost": None,
        "currency": None,
    }


def _remote_category(
    stderr: str,
    parsed: ParsedEventStream | None,
) -> ModelErrorCategory:
    text = " ".join(
        [
            stderr,
            *(parsed.error_messages if parsed is not None else ()),
        ]
    ).lower()
    if any(marker in text for marker in ("unauthorized", "authentication", "login", "401")):
        return ModelErrorCategory.AUTHENTICATION
    if any(marker in text for marker in ("rate limit", "too many requests", "429")):
        return ModelErrorCategory.RATE_LIMIT
    if any(
        marker in text
        for marker in ("connection", "transport", "network", "unavailable", "502", "503")
    ):
        return ModelErrorCategory.TRANSPORT
    return ModelErrorCategory.INTERNAL


def _safe_remote_message(
    stderr: str,
    parsed: ParsedEventStream | None,
) -> str:
    if parsed is not None and parsed.error_messages:
        return parsed.error_messages[0]
    clean = redact_text(stderr).strip()
    return clean[:4096] or "Codex CLI exited without a safe error message"


def _failed_process(message: str) -> CodexProcessResult:
    return CodexProcessResult(
        arguments=(),
        exit_code=None,
        stdout="",
        stderr=redact_text(message),
        duration_s=0.0,
        timed_out=False,
        stdout_truncated=False,
        stderr_truncated=False,
        process_group_cleaned=True,
    )


__all__ = ["CodexExecModelClient"]
