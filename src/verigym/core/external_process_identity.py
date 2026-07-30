"""Pure lifecycle resolvers for runtime-owned external process identities."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.schemas.external_agent import (
    ExternalProcessIdentityPreview,
    ExternalProcessInvocationSpec,
    ExternalProcessPayloadBinding,
    ExternalProcessRequest,
)


def resolve_external_process_invocation_spec(
    **static_values: Any,
) -> ExternalProcessInvocationSpec:
    """Freeze payload-independent process fields without constructing a request."""

    values = dict(static_values)
    values.setdefault("schema_version", "1.0")
    values.pop("invocation_spec_hash", None)
    provisional = ExternalProcessInvocationSpec.model_construct(
        **values,
        invocation_spec_hash="0" * 64,
    )
    normalized = provisional.model_dump(mode="json", exclude={"invocation_spec_hash"})
    return ExternalProcessInvocationSpec.model_validate(
        {**normalized, "invocation_spec_hash": content_hash(normalized)}
    )


def preview_external_process_identity(
    spec: ExternalProcessInvocationSpec,
) -> ExternalProcessIdentityPreview:
    """Return an explicitly unbound, non-launchable identity preview."""

    base = {
        "schema_version": "1.0",
        "invocation_spec_hash": spec.invocation_spec_hash,
        "payload_state": "unbound",
        "stdin_sha256": None,
        "stdin_utf8_bytes": None,
        "payload_binding_hash": None,
        "launch_authorized": False,
    }
    return ExternalProcessIdentityPreview.model_validate(
        {**base, "preview_hash": content_hash(base)}
    )


def bind_external_process_payload(
    spec: ExternalProcessInvocationSpec,
    rendered_prompt: str,
    *,
    template_hash: str,
    input_dataset_hash: str,
) -> ExternalProcessPayloadBinding:
    """Bind one non-empty rendered UTF-8 prompt to a static invocation."""

    if not rendered_prompt or not rendered_prompt.strip():
        raise ValueError("external process prompt must contain non-whitespace text")
    encoded = rendered_prompt.encode("utf-8")
    if len(encoded) > 2 * 1024 * 1024:
        raise ValueError("external process prompt exceeds the executable request limit")
    stdin_hash = hashlib.sha256(encoded).hexdigest()
    base = {
        "schema_version": "1.0",
        "invocation_spec_hash": spec.invocation_spec_hash,
        "payload_state": "bound",
        "stdin_sha256": stdin_hash,
        "stdin_utf8_bytes": len(encoded),
        "prompt_contract_id": spec.prompt_contract_id,
        "template_hash": template_hash,
        "input_dataset_hash": input_dataset_hash,
        "rendered_prompt_hash": stdin_hash,
    }
    return ExternalProcessPayloadBinding.model_validate(
        {**base, "payload_binding_hash": content_hash(base)}
    )


def build_external_process_request(
    spec: ExternalProcessInvocationSpec,
    payload_binding: ExternalProcessPayloadBinding,
    rendered_prompt: str,
    *,
    executable_path: Path,
) -> ExternalProcessRequest:
    """Create the sole launchable object after independently checking payload identity."""

    if payload_binding.invocation_spec_hash != spec.invocation_spec_hash:
        raise ValueError("external payload binding targets another invocation specification")
    if payload_binding.prompt_contract_id != spec.prompt_contract_id:
        raise ValueError("external payload binding uses another prompt contract")
    encoded = rendered_prompt.encode("utf-8")
    if (
        not rendered_prompt
        or not rendered_prompt.strip()
        or hashlib.sha256(encoded).hexdigest() != payload_binding.stdin_sha256
        or len(encoded) != payload_binding.stdin_utf8_bytes
    ):
        raise ValueError("rendered prompt differs from the frozen payload binding")
    static = spec.model_dump(
        mode="json",
        exclude={
            "invocation_spec_hash",
            "prompt_contract_id",
            "expected_output_schema_hash",
            "executable_path_identity",
        },
    )
    return ExternalProcessRequest.model_validate(
        {
            **static,
            "executable_path": executable_path,
            "stdin_text": rendered_prompt,
            "prompt_text_sha256": (
                payload_binding.stdin_sha256 if spec.prompt_policy is not None else None
            ),
            "invocation_spec": spec.model_dump(mode="json"),
            "payload_binding": payload_binding.model_dump(mode="json"),
            "invocation_spec_hash": spec.invocation_spec_hash,
            "payload_binding_hash": payload_binding.payload_binding_hash,
            "stdin_utf8_bytes": payload_binding.stdin_utf8_bytes,
        }
    )


def validate_external_process_request_identity(
    request: ExternalProcessRequest,
) -> ExternalProcessRequest:
    """Reconstruct a lifecycle-bound request and require byte-identical semantics."""

    if request.invocation_spec is None or request.payload_binding is None:
        raise ValueError("external process request lacks lifecycle identity")
    rebuilt = build_external_process_request(
        request.invocation_spec,
        request.payload_binding,
        request.stdin_text,
        executable_path=request.executable_path,
    )
    if rebuilt != request:
        raise ValueError("external process request lifecycle reconstruction changed")
    return request


__all__ = [
    "bind_external_process_payload",
    "build_external_process_request",
    "preview_external_process_identity",
    "resolve_external_process_invocation_spec",
    "validate_external_process_request_identity",
]
