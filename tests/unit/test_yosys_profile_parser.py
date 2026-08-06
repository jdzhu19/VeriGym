from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from verigym.core.errors import ConfigurationError, DuplicatePluginError
from verigym.core.hashing import content_hash
from verigym.profiles.base import (
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
)
from verigym.profiles.registry import ToolchainProfileRegistry
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.profiles.validation import validate_profile
from verigym.registry.collections import build_registries
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.common import RuntimeRequirement, ToolchainProfile
from verigym.tools.yosys.parser import YosysStatParseError, parse_yosys_stat_json
from verigym.tools.yosys.schemas import YosysSynthesisRequest
from verigym.tools.yosys.script_builder import (
    FLOW_TEMPLATE_HASH,
    build_yosys_script,
    generated_script_hash,
)

FIXTURE = Path("tests/fixtures/yosys/stat_format_compatible_067.json")


def _profile() -> ToolchainProfile:
    return build_registries(discover_external=False).profiles.get("open-yosys-toy-area-v1")


def _request(**updates: object) -> YosysSynthesisRequest:
    values: dict[str, object] = {
        "sources": ["rtl/counter.v"],
        "top": "counter",
        "liberty_asset_id": "verigym-toy-cells-v1",
        "liberty_path": ".verigym_profile/cells.lib",
        "liberty_sha256": "a" * 64,
        "area_unit": "toy_area_unit",
        "require_mapped_area": True,
    }
    values.update(updates)
    return YosysSynthesisRequest.model_validate(values)


def _resolved(asset_hash: str = "a" * 64) -> ResolvedToolchainProfile:
    unresolved = ResolvedToolchainProfile(
        profile_id="profile",
        profile_version="1",
        declared_profile_hash="b" * 64,
        resolved_profile_hash="",
        reproducibility_scope="public",
        deterministic=True,
        runtime_identity=ResolvedRuntimeIdentity(
            runtime_slug="docker",
            isolation_level="docker_standard",
            deterministic=True,
            os="linux",
            architecture="amd64",
            resolved_image_id="sha256:" + "c" * 64,
            network_policy="none",
            resource_controls=True,
            security_hash="d" * 64,
            resource_contract_hash="e" * 64,
        ),
        tool_identities=[
            ResolvedToolIdentity(
                logical_name="yosys",
                executable="yosys",
                version="0.67",
                version_output="Yosys 0.67",
                git_hash="f" * 40,
                capabilities=["synth"],
                identity_kind="immutable_image_observation",
            )
        ],
        asset_identities=[
            ResolvedArtifactIdentity(
                logical_id="cells",
                media_type="application/x-liberty",
                source_kind="package_resource",
                content_hash=asset_hash,
                redistributable=True,
                unit="toy_area_unit",
                copy_permitted=True,
            )
        ],
        flow_hash="1" * 64,
        metric_contract_hash="2" * 64,
        reference_contract_hash="3" * 64,
        flow_template_id="verigym-yosys-area-v1",
        generated_script_hash="4" * 64,
        top_module="counter",
        source_paths=["rtl/counter.v"],
        metric_scope="synthesis_area_only",
        area_unit="toy_area_unit",
        reference_strategy="suite_reference_solution",
        reference_candidate_hash="5" * 64,
    )
    return unresolved.model_copy(
        update={"resolved_profile_hash": content_hash(unresolved.identity_payload())}
    )


def test_builtin_profile_is_strict_valid_and_round_trips() -> None:
    profile = _profile()
    assert validate_profile(profile).valid
    assert ToolchainProfile.model_validate_json(profile.model_dump_json()) == profile
    payload = profile.model_dump(mode="json")
    payload["unknown_contract"] = True
    with pytest.raises(ValidationError, match="unknown_contract"):
        ToolchainProfile.model_validate(payload)
    payload = profile.model_dump(mode="json")
    payload["schema_version"] = "99.0"
    with pytest.raises(ValidationError, match="unsupported toolchain-profile schema"):
        ToolchainProfile.model_validate(payload)
    payload = profile.model_dump(mode="json")
    payload["api_version"] = "99.0"
    with pytest.raises(ValidationError, match="unsupported toolchain-profile API"):
        ToolchainProfile.model_validate(payload)


def test_profile_registry_refuses_duplicates_and_missing_ids() -> None:
    profile = _profile()
    with pytest.raises(DuplicatePluginError, match="duplicate toolchain profile"):
        ToolchainProfileRegistry([profile, profile])
    with pytest.raises(Exception, match="is not registered"):
        ToolchainProfileRegistry().get("missing")


def test_profile_file_loader_is_bounded_and_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    profile = _profile()
    profile_file = tmp_path / "profile.json"
    profile_file.write_text(profile.model_dump_json(), encoding="utf-8")
    loaded = ToolchainProfileRegistry().load_file(profile_file)
    assert loaded == profile

    duplicate = tmp_path / "duplicate.json"
    payload = profile.model_dump_json().replace(
        f'"id":"{profile.id}"',
        f'"id":"duplicate","id":"{profile.id}"',
        1,
    )
    duplicate.write_text(payload, encoding="utf-8")
    with pytest.raises(ConfigurationError, match="duplicate toolchain-profile key"):
        ToolchainProfileRegistry().load_file(duplicate)

    link = tmp_path / "profile-link.json"
    link.symlink_to(profile_file)
    with pytest.raises(ConfigurationError, match="non-symlink"):
        ToolchainProfileRegistry().load_file(link)


def test_profile_rejects_malformed_hashes_and_changed_tool_contracts() -> None:
    payload = _profile().model_dump(mode="json")
    payload["libraries"][0]["content_hash"] = "not-a-sha256"
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        ToolchainProfile.model_validate(payload)

    changed = _profile().model_copy(deep=True)
    changed.tools[0].version_command = ["sh", "-c", "yosys -V"]
    assert not validate_profile(changed).valid
    changed = _profile().model_copy(deep=True)
    changed.tools[0].capabilities.remove("abc")
    assert not validate_profile(changed).valid


def test_profile_asset_and_resolved_hashes_cover_changed_content() -> None:
    profile = _profile()
    changed = profile.model_copy(deep=True)
    changed.libraries[0].content_hash = "0" * 64
    assert content_hash(profile) != content_hash(changed)
    validation = validate_profile(changed)
    assert not validation.valid
    assert "hash mismatch" in " ".join(validation.errors)
    first = _resolved("a" * 64)
    second = _resolved("b" * 64)
    assert first.resolved_profile_hash != second.resolved_profile_hash
    assert first.resolved_profile_hash == content_hash(first.identity_payload())


def test_docker_ranking_profile_rejects_local_runtime_before_tool_execution() -> None:
    profile = _profile()
    with pytest.raises(ConfigurationError, match="allows runtimes"):
        resolve_toolchain_profile(
            profile,
            LocalRuntime(),
            source_paths=["rtl/counter.v"],
            top_module="counter",
            reference_candidate_hash="a" * 64,
        )


def test_site_specific_local_profile_records_executable_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile().model_copy(deep=True)
    profile.reproducibility_scope = "site_specific"
    profile.runtime = RuntimeRequirement(
        runtime="local",
        allowed_runtimes=["local"],
        minimum_isolation_level="local_trusted",
        immutable_image_required=False,
        network_policy=None,
        resource_controls_required=False,
    )
    profile.container_image = None
    identities = [
        ResolvedToolIdentity(
            logical_name="yosys",
            executable="yosys",
            version="0.67",
            version_output="Yosys 0.67+post (git sha1 b8e7da6f40ae8f552c116bf6c359b07c6533e159)",
            git_hash="b8e7da6f40ae8f552c116bf6c359b07c6533e159",
            executable_sha256="6" * 64,
            capabilities=["synth", "stat_json", "liberty", "abc"],
            identity_kind="local_executable",
        ),
        ResolvedToolIdentity(
            logical_name="yosys-abc",
            executable="yosys-abc",
            version="1.01",
            version_output="UC Berkeley, ABC 1.01",
            git_hash="e026ed5380f3bdc3beea2ff9ffc23236fc549d5b",
            executable_sha256="7" * 64,
            capabilities=["liberty_mapping"],
            identity_kind="local_executable",
        ),
    ]
    monkeypatch.setattr(
        "verigym.profiles.resolver.resolve_local_tool_identities",
        lambda: identities,
    )
    validation = validate_profile(profile)
    assert validation.valid
    assert "exploratory" in " ".join(validation.warnings)
    resolved = resolve_toolchain_profile(
        profile,
        LocalRuntime(),
        source_paths=["rtl/counter.v"],
        top_module="counter",
        reference_candidate_hash="a" * 64,
    )
    assert resolved.runtime_identity.runtime_slug == "local"
    assert resolved.runtime_identity.resolved_image_id is None
    assert all(tool.identity_kind == "local_executable" for tool in resolved.tool_identities)


def test_script_is_deterministic_fixed_and_has_no_exec_or_original_paths() -> None:
    request = _request(sources=["rtl/name with ; quotes ' []\n.v"])
    first = build_yosys_script(request)
    second = build_yosys_script(request.model_copy(deep=True))
    assert first == second
    assert generated_script_hash(request) == generated_script_hash(request.model_copy())
    assert "src/0000.v" in first
    assert request.sources[0] not in first
    assert " exec " not in f" {first.lower()} "
    assert FLOW_TEMPLATE_HASH == "0e825470addb47375b7fed24681f6869c793cc996066a6aed22cff9f8ba6ecd0"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("top", "counter; exec touch_owned"),
        ("top", "\\escaped"),
        ("defines", {"BAD;exec": "1"}),
        ("defines", {"GOOD": "1;exec"}),
        ("include_dirs", ["../include"]),
    ],
)
def test_request_rejects_script_injection_fields(field: str, value: object) -> None:
    values = _request().model_dump(mode="json")
    values[field] = value
    with pytest.raises(ValidationError):
        YosysSynthesisRequest.model_validate(values)


def test_request_forbids_custom_commands_and_hash_typos() -> None:
    values = _request().model_dump(mode="json")
    values["yosys_commands"] = ["exec touch /tmp/owned"]
    with pytest.raises(ValidationError, match="yosys_commands"):
        YosysSynthesisRequest.model_validate(values)
    values = _request().model_dump(mode="json")
    values["liberty_sha256"] = "not-a-hash"
    with pytest.raises(ValidationError, match="SHA-256"):
        YosysSynthesisRequest.model_validate(values)


def test_parser_reads_structural_counts_histogram_and_liberty_area() -> None:
    parsed = parse_yosys_stat_json(
        FIXTURE.read_bytes(), top="counter", expected_yosys_version="0.67"
    )
    assert parsed.num_wires == 30
    assert parsed.num_wire_bits == 37
    assert parsed.num_cells == 35
    assert parsed.cells_by_type["VG_DFF"] == 8
    assert parsed.area == 87.0


def test_parser_allows_area_absence_without_calling_cell_count_area() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["additive_future_field"] = {"ignored": True}
    payload["design"].pop("area")
    parsed = parse_yosys_stat_json(json.dumps(payload).encode(), top="counter")
    assert parsed.area is None
    assert parsed.num_cells == 35


@pytest.mark.parametrize("area", [0, -1, math.nan, math.inf, -math.inf])
def test_parser_rejects_invalid_area(area: float) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["design"]["area"] = area
    with pytest.raises(YosysStatParseError, match="area|constant"):
        parse_yosys_stat_json(json.dumps(payload).encode(), top="counter")


def test_parser_rejects_malformed_truncated_oversized_and_deep_json() -> None:
    with pytest.raises(YosysStatParseError, match="malformed"):
        parse_yosys_stat_json(b'{"creator":', top="counter")
    with pytest.raises(YosysStatParseError, match="byte limit"):
        parse_yosys_stat_json(FIXTURE.read_bytes(), top="counter", max_bytes=10)
    nested: object = "leaf"
    for _ in range(40):
        nested = {"nested": nested}
    with pytest.raises(YosysStatParseError, match="nesting-depth"):
        parse_yosys_stat_json(json.dumps(nested).encode(), top="counter")


def test_parser_rejects_missing_fields_histogram_mismatch_and_version() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del payload["design"]["num_wire_bits"]
    with pytest.raises(YosysStatParseError, match="num_wire_bits"):
        parse_yosys_stat_json(json.dumps(payload).encode(), top="counter")
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["design"]["num_cells"] = 36
    with pytest.raises(YosysStatParseError, match="histogram"):
        parse_yosys_stat_json(json.dumps(payload).encode(), top="counter")
    with pytest.raises(YosysStatParseError, match="incompatible"):
        parse_yosys_stat_json(FIXTURE.read_bytes(), top="counter", expected_yosys_version="9.99")
