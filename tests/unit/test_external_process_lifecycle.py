from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from verigym.core.external_process_identity import (
    bind_external_process_payload,
    build_external_process_request,
    preview_external_process_identity,
    resolve_external_process_invocation_spec,
    validate_external_process_request_identity,
)
from verigym.core.hashing import content_hash
from verigym.schemas.external_agent import ExternalProcessRequest


def _spec(**updates: object):
    values: dict[str, object] = {
        "protocol": "codex_app_server_remote_environment_v1",
        "runtime_role": "agent",
        "argv": ["/usr/local/bin/codex", "exec-server", "--listen", "stdio://"],
        "logical_cwd": "/workspace",
        "stdin_transport": "runtime_protocol_adapter",
        "network_policy": "none",
        "mount_policy": "task_workspace_only",
        "writable_destinations": ["/workspace", "/tmp"],
        "read_only_mounts": [],
        "container_environment_names": [],
        "integration_track": "codex_cli_readonly_single_turn_agent",
        "workspace_mode": "fresh_empty",
        "logical_workspace_root": "/workspace",
        "requested_model_id": "gpt-5.4",
        "requested_reasoning_effort": "xhigh",
        "executable_path_identity": "verified_host_codex_cli",
        "executable_name": "codex.js",
        "executable_sha256": "a" * 64,
        "executable_version": "codex-cli 0.144.6",
        "capability_fingerprint": "b" * 64,
        "requested_auth_mode": "chatgpt_cli_session",
        "resolved_auth_mode": "inherited_codex_login",
        "auth_semantic_id": "codex.auth.inherited_chatgpt_session.v1",
        "allow_proxy_environment": True,
        "forwarded_proxy_environment_names": ["HTTP_PROXY", "HTTPS_PROXY"],
        "timeout_s": 300,
        "max_output_bytes": 131_072,
        "editable_globs": [],
        "readonly_globs": [],
        "prompt_policy": None,
        "prompt_policy_hash": None,
        "prompt_contract_id": "evolve_context_memory_builder_v1",
        "expected_output_schema_hash": "c" * 64,
    }
    values.update(updates)
    return resolve_external_process_invocation_spec(**values)


def _binding(spec=None, prompt: str = "Return one strict JSON memory pack."):
    resolved = spec or _spec()
    return bind_external_process_payload(
        resolved,
        prompt,
        template_hash="d" * 64,
        input_dataset_hash="e" * 64,
    )


def test_static_preview_is_unbound_and_never_constructs_request() -> None:
    spec = _spec()
    preview = preview_external_process_identity(spec)

    assert preview.payload_state == "unbound"
    assert preview.stdin_sha256 is None
    assert preview.stdin_utf8_bytes is None
    assert preview.payload_binding_hash is None
    assert preview.launch_authorized is False


def test_executable_request_permanently_rejects_empty_stdin() -> None:
    spec = _spec()
    binding = _binding(spec)
    valid = build_external_process_request(
        spec,
        binding,
        "Return one strict JSON memory pack.",
        executable_path=Path("/usr/local/bin/codex"),
    )
    payload = valid.model_dump(mode="json")
    payload["stdin_text"] = ""

    with pytest.raises(ValidationError, match="at least 1 character"):
        ExternalProcessRequest.model_validate(payload)


def test_payload_binding_rejects_whitespace_and_detects_hash_or_length_mutation() -> None:
    spec = _spec()
    with pytest.raises(ValueError, match="non-whitespace"):
        _binding(spec, " \t\n")

    binding = _binding(spec)
    with pytest.raises(ValueError, match="differs from the frozen payload"):
        build_external_process_request(
            spec,
            binding,
            "A changed prompt.",
            executable_path=Path("/usr/local/bin/codex"),
        )


def test_prompt_contract_and_output_schema_are_static_identity() -> None:
    first = _spec()
    changed_contract = _spec(prompt_contract_id="another_contract")
    changed_schema = _spec(expected_output_schema_hash="f" * 64)

    assert first.invocation_spec_hash != changed_contract.invocation_spec_hash
    assert first.invocation_spec_hash != changed_schema.invocation_spec_hash
    with pytest.raises(
        ValueError, match="another invocation specification|another prompt contract"
    ):
        build_external_process_request(
            changed_contract,
            _binding(first),
            "Return one strict JSON memory pack.",
            executable_path=Path("/usr/local/bin/codex"),
        )


def test_executable_request_exactly_reconstructs_from_spec_and_binding() -> None:
    prompt = "Return one strict JSON memory pack."
    spec = _spec()
    binding = _binding(spec, prompt)
    request = build_external_process_request(
        spec,
        binding,
        prompt,
        executable_path=Path("/usr/local/bin/codex"),
    )

    assert request.invocation_spec_hash == spec.invocation_spec_hash
    assert request.payload_binding_hash == binding.payload_binding_hash
    assert request.stdin_utf8_bytes == len(prompt.encode("utf-8"))
    assert validate_external_process_request_identity(request) == request


def test_historical_empty_stdin_fixture_fails_before_ledger_authorization(
    tmp_path: Path,
) -> None:
    fixture = json.loads(
        Path("tests/fixtures/m10b_memory_builder_empty_stdin_preview.json").read_text()
    )
    spec = _spec()
    binding = _binding(spec)
    payload = build_external_process_request(
        spec,
        binding,
        "Return one strict JSON memory pack.",
        executable_path=Path("/usr/local/bin/codex"),
    ).model_dump(mode="json")
    payload["stdin_text"] = fixture["stdin_text"]
    ledger = tmp_path / "model-process-ledger.jsonl"

    with pytest.raises(ValidationError):
        ExternalProcessRequest.model_validate(payload)
    assert fixture["memory_process_authorizations"] == 0
    assert fixture["model_processes_started"] == 0
    assert not ledger.exists()


def test_identity_resolution_is_deterministic() -> None:
    first = _spec()
    second = _spec()
    assert first == second
    assert content_hash(first) == content_hash(second)
