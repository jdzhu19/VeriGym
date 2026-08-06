from types import SimpleNamespace

import pytest

from verigym.core.errors import ReplayError
from verigym.core.hashing import hash_bytes
from verigym.core.replay import _validate_stored_synthesis_artifacts
from verigym.schemas.synthesis import SynthesisArtifactRef, SynthesisMetrics


def test_replay_resolves_tool_neutral_synthesis_artifact_namespace(tmp_path) -> None:
    backend = tmp_path / "artifacts" / "commercial_backend"
    candidate_root = backend / "candidate"
    candidate_root.mkdir(parents=True)
    flow = b"tool-neutral synthesis flow\n"
    (candidate_root / "flow.tcl").write_bytes(flow)
    flow_hash = hash_bytes(flow)
    summary = (
        b'{"reference_candidate_hash":"' + b"b" * 64 + b'",'
        b'"reference_netlist_exported":false,"reference_rtl_exported":false,'
        b'"resolved_profile_hash":"' + b"a" * 64 + b'","schema_version":"1.0"}\n'
    )
    (backend / "reference_summary.json").write_bytes(summary)
    candidate = SynthesisMetrics(
        status="passed",
        synthesis_ok=True,
        role="candidate",
        top="dut",
        generated_script_hash=flow_hash,
        artifacts=[
            SynthesisArtifactRef(
                path="flow.tcl",
                content_hash=flow_hash,
                size_bytes=len(flow),
                role="generated_script",
                visibility="public",
            )
        ],
    )
    manifest = SimpleNamespace(
        synthesis_flow_script_hash=flow_hash,
        reference_summary_hash=hash_bytes(summary),
        resolved_profile_hash="a" * 64,
        reference_candidate_hash="b" * 64,
    )
    scorecard = SimpleNamespace(
        quality=SimpleNamespace(
            synthesis=candidate,
            reference_synthesis=SimpleNamespace(artifacts=[]),
        )
    )

    _validate_stored_synthesis_artifacts(tmp_path, manifest, scorecard)

    (candidate_root / "flow.tcl").write_bytes(b"changed\n")
    with pytest.raises(ReplayError, match="stored candidate synthesis artifact changed"):
        _validate_stored_synthesis_artifacts(tmp_path, manifest, scorecard)
