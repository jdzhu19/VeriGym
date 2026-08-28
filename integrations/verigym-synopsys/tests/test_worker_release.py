from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError
from verigym.plugin_api import content_hash

from verigym_synopsys.agent_worker_protocol import (
    AgentWorkerIsolationContract,
    AgentWorkerLaunchRequest,
    AgentWorkerReceipt,
    agent_worker_contract_identity_payload,
)
from verigym_synopsys.worker_release import (
    COMMERCIAL_WORKER_RELEASE_PROTOCOL,
    build_commercial_worker_release,
    materialize_commercial_worker_release,
    verify_commercial_worker_release,
)

_HASH = "a" * 64


def _release(*, worker_code: bytes = b"worker-v1"):
    return build_commercial_worker_release(
        server_code={"server.py": b"server-v1"},
        worker_code={"worker.py": worker_code},
        startup_script=b"#!/bin/sh\nexec worker\n",
        profile_bundle={"profile.yaml": b"sanitized-profile"},
        remote_tools={"dc": {"identity": "remote-hash"}},
        asset_manifest={"library": "b" * 64, "constraints": "c" * 64},
        worker_contract={"one_candidate": True},
        worker_isolation_contract={"isolation": "lsf_job"},
    )


def test_commercial_worker_release_is_stable_and_code_bound() -> None:
    first = _release()
    second = _release()
    changed = _release(worker_code=b"worker-v2")

    assert first == second
    assert first.release_hash != changed.release_hash
    assert first.worker_code_hash != changed.worker_code_hash
    assert set(first.safe_dict()) == {
        "protocol",
        "server_code_hash",
        "worker_code_hash",
        "startup_script_hash",
        "profile_bundle_hash",
        "remote_tools_hash",
        "asset_manifest_hash",
        "worker_contract_hash",
        "worker_isolation_contract_hash",
        "bundle_hash",
        "release_hash",
    }
    verify_commercial_worker_release(first, first.release_hash)
    with pytest.raises(ValueError, match="differs"):
        verify_commercial_worker_release(first, changed.release_hash)


def test_commercial_asset_manifest_rejects_content_and_paths() -> None:
    values = {
        "server_code": b"server",
        "worker_code": b"worker",
        "startup_script": b"startup",
        "profile_bundle": b"profile",
        "remote_tools": {"dc": _HASH},
        "worker_contract": {"one_candidate": True},
        "worker_isolation_contract": {"isolation": "lsf_job"},
    }

    with pytest.raises(ValueError, match="non-hash"):
        build_commercial_worker_release(
            **values,
            asset_manifest={"library": "/site/secret/library.db"},
        )


def test_materialized_release_is_read_only_and_content_addressed(tmp_path: Path) -> None:
    release = _release()
    target = materialize_commercial_worker_release(
        tmp_path,
        release,
        {
            "server/server.py": b"server-v1",
            "worker/worker.py": b"worker-v1",
            "startup.sh": b"#!/bin/sh\nexec worker\n",
        },
    )

    assert target.name == release.release_hash
    assert stat.S_IMODE(target.stat().st_mode) == 0o555
    assert stat.S_IMODE((target / "release.json").stat().st_mode) == 0o444
    assert stat.S_IMODE((target / "worker" / "worker.py").stat().st_mode) == 0o444
    persisted = json.loads((target / "release.json").read_text(encoding="utf-8"))
    assert persisted == release.model_dump(mode="json")
    assert materialize_commercial_worker_release(tmp_path, release, {}) == target

    other_root = tmp_path / "other"
    with pytest.raises(ValueError, match="differ"):
        materialize_commercial_worker_release(
            other_root,
            release,
            {
                "server/server.py": b"server-v1",
                "worker/worker.py": b"tampered",
                "startup.sh": b"#!/bin/sh\nexec worker\n",
            },
        )


def test_worker_protocol_accepts_v1_and_requires_paired_v2_release() -> None:
    legacy = AgentWorkerIsolationContract(
        isolation_kind="lsf_job",
        launcher_version="0.1.0",
        code_identity_hash=_HASH,
        isolation_profile_hash="b" * 64,
        network_policy="site_license_controlled",
        max_wall_seconds=900,
        memory_mb=1024,
        cores=1,
    )
    assert legacy.release_hash is None
    assert "release_protocol" not in agent_worker_contract_identity_payload(legacy)
    assert "release_hash" not in agent_worker_contract_identity_payload(legacy)
    release = _release()
    current = legacy.model_copy(
        update={
            "release_protocol": COMMERCIAL_WORKER_RELEASE_PROTOCOL,
            "release_hash": release.release_hash,
        }
    )
    assert current.release_hash == release.release_hash
    assert agent_worker_contract_identity_payload(current)["release_hash"] == release.release_hash
    with pytest.raises(ValidationError, match="supplied together"):
        AgentWorkerIsolationContract.model_validate(
            {**legacy.model_dump(mode="json"), "release_hash": release.release_hash}
        )

    request = AgentWorkerLaunchRequest(
        contract_hash=_HASH,
        code_identity_hash=_HASH,
        isolation_profile_hash=_HASH,
        request_hash=_HASH,
        source_bundle_hash=_HASH,
        synthesis={},
    )
    assert request.expected_release_hash is None
    receipt = AgentWorkerReceipt(
        contract_hash=_HASH,
        code_identity_hash=_HASH,
        isolation_profile_hash=_HASH,
        request_hash=_HASH,
        source_bundle_hash=_HASH,
        dispatch_id_hash=content_hash("dispatch"),
        scheduler_dispatched=True,
        worker_started=True,
        worker_completed=True,
        cleanup_complete=True,
        lifecycle="completed_clean",
        duration_s=1.0,
    )
    assert receipt.release_hash is None
