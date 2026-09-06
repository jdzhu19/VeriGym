from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.profiles.base import (
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
)
from verigym.profiles.identity import (
    RESOLVED_PROFILE_IDENTITY_COMPONENTS,
    ResolvedProfileIdentityComponent,
    compare_resolved_profile_identity,
    require_resolved_profile_identity,
)


def _resolved() -> ResolvedToolchainProfile:
    unresolved = ResolvedToolchainProfile(
        profile_id="commercial-profile",
        profile_version="1.0.0",
        declared_profile_hash="a" * 64,
        resolved_profile_hash="",
        reproducibility_scope="site_specific",
        deterministic=True,
        runtime_identity=ResolvedRuntimeIdentity(
            runtime_slug="docker",
            isolation_level="docker_standard",
            deterministic=True,
            os="linux",
            architecture="amd64",
            resolved_image_id="sha256:" + "b" * 64,
            network_policy="none",
            resource_controls=True,
            security_hash="c" * 64,
            resource_contract_hash="d" * 64,
        ),
        tool_identities=[
            ResolvedToolIdentity(
                logical_name="synopsys-dc-mcp",
                executable="mcp-client",
                version="bound",
                version_output="bound",
                executable_sha256="e" * 64,
                identity_kind="local_executable",
            ),
            ResolvedToolIdentity(
                logical_name="design-compiler",
                executable="remote",
                version="bound",
                version_output="bound",
                identity_kind="immutable_image_observation",
            ),
        ],
        asset_identities=[
            ResolvedArtifactIdentity(
                logical_id="library",
                media_type="application/x-synopsys-db",
                source_kind="external_path",
                content_hash="f" * 64,
                redistributable=False,
                copy_permitted=False,
            )
        ],
        flow_hash="1" * 64,
        metric_contract_hash="2" * 64,
        reference_contract_hash="3" * 64,
        flow_template_id="verigym-dc-area-timing-v1",
        generated_script_hash="4" * 64,
        top_module="counter",
        source_paths=["rtl/counter.v"],
        synthesis_source_projection_hash="5" * 64,
        metric_scope="synthesis_area_timing",
        area_unit="um^2",
        timing_unit="ns",
        reference_strategy="suite_reference_solution",
        reference_candidate_hash="6" * 64,
        metadata={
            "mcp_transport_sha256": "7" * 64,
            "mcp_server_release_hash": "8" * 64,
            "remote_tool_versions": {"dc": "9" * 64},
            "remote_asset_hashes": {"library": "a" * 64},
            "agent_feedback_worker_release_hash": "b" * 64,
        },
    )
    return _rehash(unresolved)


def _rehash(profile: ResolvedToolchainProfile) -> ResolvedToolchainProfile:
    blank = profile.model_copy(update={"resolved_profile_hash": ""}, deep=True)
    return blank.model_copy(
        update={"resolved_profile_hash": content_hash(blank.identity_payload())}, deep=True
    )


Mutation = Callable[[ResolvedToolchainProfile], ResolvedToolchainProfile]


def _metadata(key: str, value: object) -> Mutation:
    def mutate(profile: ResolvedToolchainProfile) -> ResolvedToolchainProfile:
        metadata = {**profile.metadata, key: value}
        return _rehash(profile.model_copy(update={"metadata": metadata}, deep=True))

    return mutate


@pytest.mark.parametrize(
    ("component", "mutate"),
    [
        (
            "runtime",
            lambda profile: _rehash(
                profile.model_copy(
                    update={
                        "runtime_identity": profile.runtime_identity.model_copy(
                            update={"security_hash": "0" * 64}
                        )
                    },
                    deep=True,
                )
            ),
        ),
        ("transport", _metadata("mcp_transport_sha256", "0" * 64)),
        ("server_release", _metadata("mcp_server_release_hash", "0" * 64)),
        ("remote_tools", _metadata("remote_tool_versions", {"dc": "0" * 64})),
        ("remote_assets", _metadata("remote_asset_hashes", {"library": "0" * 64})),
        (
            "flow",
            lambda profile: _rehash(profile.model_copy(update={"flow_hash": "0" * 64})),
        ),
        (
            "reference",
            lambda profile: _rehash(
                profile.model_copy(update={"reference_candidate_hash": "0" * 64})
            ),
        ),
        ("worker_contract", _metadata("agent_feedback_worker_release_hash", "0" * 64)),
        (
            "source_projection",
            lambda profile: _rehash(
                profile.model_copy(update={"synthesis_source_projection_hash": "0" * 64})
            ),
        ),
    ],
)
def test_resolved_profile_identity_classifies_each_component(
    component: ResolvedProfileIdentityComponent,
    mutate: Mutation,
) -> None:
    expected = _resolved()
    evidence = compare_resolved_profile_identity(expected, mutate(expected))

    assert evidence.changed_components == [component]
    assert not evidence.matches
    with pytest.raises(ConfigurationError, match=component):
        require_resolved_profile_identity(expected, mutate(expected))


def test_resolved_profile_comparison_evidence_is_hash_only() -> None:
    expected = _resolved().model_copy(update={"source_paths": ["secret/site/pdk/counter.v"]})
    expected = _rehash(expected)
    observed = _rehash(expected.model_copy(update={"top_module": "counter_v2"}))

    payload = compare_resolved_profile_identity(expected, observed).model_dump(mode="json")
    serialized = json.dumps(payload)

    assert set(payload) == {"expected_hash", "observed_hash", "changed_components"}
    assert "secret" not in serialized
    assert payload["changed_components"] == ["source_projection"]


def test_resolved_profile_identity_is_stable() -> None:
    profile = _resolved()
    evidence = require_resolved_profile_identity(profile, profile.model_copy(deep=True))

    assert evidence.matches
    assert evidence.changed_components == []
    assert tuple(RESOLVED_PROFILE_IDENTITY_COMPONENTS) == (
        "runtime",
        "transport",
        "server_release",
        "remote_tools",
        "remote_assets",
        "flow",
        "reference",
        "worker_contract",
        "source_projection",
    )
