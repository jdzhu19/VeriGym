from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash

from verigym_training_reference.schemas import SftMessage, VerifiedSftExample
from verigym_training_reference.sft_exporter import _reject_forbidden, export_verified_solution_sft

HASH = "a" * 64


def _write_hashed(path: Path, base: dict[str, object], field: str) -> str:
    identity = content_hash(base)
    path.write_text(json.dumps({**base, field: identity}), encoding="utf-8")
    return identity


def test_sft_example_requires_a_final_assistant_message() -> None:
    with pytest.raises(ValidationError, match="assistant"):
        VerifiedSftExample(
            sample_id=HASH,
            task_id="suite/task",
            official_task_id="official/task",
            task_hash=HASH,
            source_hash=HASH,
            verifier_hash=HASH,
            candidate_path="rtl/TopModule.sv",
            candidate_sha256=HASH,
            verigym_candidate_hash=HASH,
            source_model_id="gpt-5.6-luna",
            source_reasoning_effort="max",
            model_call_hash=HASH,
            public_input_hash=HASH,
            messages=[
                SftMessage(role="system", content="design RTL"),
                SftMessage(role="user", content="implement it"),
            ],
            example_hash=HASH,
        )


def test_sft_export_rejects_an_unresolved_sample_before_artifact_access(
    tmp_path: Path,
) -> None:
    public_hash = _write_hashed(
        tmp_path / "public-input.json",
        {
            "task_id": "suite/task",
            "candidate_path": "rtl/TopModule.sv",
            "task_description": "Implement it.",
            "public_readme": "Public only.",
            "candidate_skeleton": "module TopModule; endmodule\n",
            "hidden_assets_included": False,
        },
        "record_hash",
    )
    model_hash = _write_hashed(
        tmp_path / "model-call.json",
        {
            "requested_model_id": "gpt-5.6-luna",
            "requested_reasoning_effort": "max",
        },
        "record_hash",
    )
    _write_hashed(
        tmp_path / "sampling-summary.json",
        {
            "resolved": False,
            "infrastructure_invalid": False,
            "model_call_hash": model_hash,
            "public_input_hash": public_hash,
        },
        "summary_hash",
    )

    with pytest.raises(ConfigurationError, match="resolved"):
        export_verified_solution_sft(tmp_path, tmp_path / "output")


@pytest.mark.parametrize(
    "payload",
    [
        b"-----BEGIN " + b"PRIVATE KEY-----",
        b"sk-" + b"x" * 30,
        b"https://" + b"user:password@example.invalid/resource",
    ],
)
def test_sft_export_rejects_credential_patterns(payload: bytes) -> None:
    with pytest.raises(ConfigurationError):
        _reject_forbidden(payload, label="fixture")
