from types import SimpleNamespace

import pytest

from verigym.core.errors import ReplayError
from verigym.core.hashing import hash_bytes
from verigym.core.replay import (
    _is_external_workspace_quarantine,
    _validate_stored_synthesis_artifacts,
)
from verigym.schemas.synthesis import SynthesisArtifactRef, SynthesisMetrics
from verigym.schemas.verifier import VerifierStatus


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


def test_replay_accepts_profile_run_quarantined_before_synthesis(tmp_path) -> None:
    manifest = SimpleNamespace(reference_summary_hash=None)
    scorecard = SimpleNamespace(
        status="failed",
        resolved=False,
        termination_reason="policy_violation",
        quality=SimpleNamespace(synthesis=None, reference_synthesis=None),
        verifier_results=[
            SimpleNamespace(
                status=VerifierStatus.SKIPPED,
                message="candidate quarantined after external workspace policy violation",
            )
        ],
    )

    _validate_stored_synthesis_artifacts(tmp_path, manifest, scorecard)
    assert _is_external_workspace_quarantine(scorecard)

    scorecard.termination_reason = "runtime_error"
    assert not _is_external_workspace_quarantine(scorecard)
    with pytest.raises(ReplayError, match="no candidate synthesis record"):
        _validate_stored_synthesis_artifacts(tmp_path, manifest, scorecard)
