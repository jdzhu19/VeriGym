from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.prepare_nangate45_ppa_profile import main as prepare_nangate45_profile
from verigym.core.errors import ConfigurationError, DuplicatePluginError
from verigym.core.hashing import content_hash, hash_bytes
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
from verigym.tools.yosys.opensta import (
    COMPATIBILITY_FLOW_TEMPLATE_CONTRACT,
    COMPATIBILITY_FLOW_TEMPLATE_ID,
    LATCH_MAPPING_FLOW_TEMPLATE_CONTRACT,
    LATCH_MAPPING_FLOW_TEMPLATE_ID,
    LATCH_MAPPING_SOURCE,
    LEGACY_FLOW_TEMPLATE_CONTRACT,
    LEGACY_FLOW_TEMPLATE_ID,
    build_opensta_script,
    parse_opensta_metrics,
    parse_opensta_power_json,
)
from verigym.tools.yosys.opensta import (
    FLOW_TEMPLATE_ID as OPENSTA_FLOW_TEMPLATE_ID,
)
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


def _opensta_request(**updates: object) -> YosysSynthesisRequest:
    values = _request().model_dump(mode="json")
    values.update(
        {
            "flow_template_id": OPENSTA_FLOW_TEMPLATE_ID,
            "constraints_path": ".verigym_profile/constraints.sdc",
            "constraints_sha256": "b" * 64,
            "timing_unit": "ns",
            "power_unit": "uW",
            "clock_name": "clk",
            "clock_period": 10.0,
            "wire_load_model": "5K_hvratio_1_1",
            "power_activity_mode": "global_clock_relative",
            "power_activity": 0.1,
            "power_duty": 0.5,
            "opensta_executable": "/opt/opensta/bin/sta",
            "opensta_executable_sha256": "c" * 64,
            "expected_opensta_version": "3.1.0",
        }
    )
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


def test_nangate_preparer_binds_opensta_binary_into_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdk = tmp_path / "pdk"
    liberty = pdk / "Front_End" / "Liberty" / "NLDM" / "NangateOpenCellLibrary_typical.lib"
    liberty.parent.mkdir(parents=True)
    liberty.write_text("library (cells) {}\n", encoding="utf-8")
    sdc = tmp_path / "counter.sdc"
    sdc.write_text("create_clock -name clk -period 10 [get_ports clk]\n", encoding="utf-8")
    opensta = tmp_path / "sta"
    opensta.write_bytes(b"fake-opensta")
    identities = [
        ResolvedToolIdentity(
            logical_name="yosys",
            executable="yosys",
            version="0.67",
            version_output="Yosys 0.67 (git sha1 abcdef)",
            git_hash="abcdef",
            executable_sha256="a" * 64,
            capabilities=["synth", "stat_json", "liberty", "abc"],
            identity_kind="local_executable",
        ),
        ResolvedToolIdentity(
            logical_name="yosys-abc",
            executable="yosys-abc",
            version="1.01",
            version_output="ABC 1.01",
            executable_sha256="b" * 64,
            capabilities=["liberty_mapping"],
            identity_kind="local_executable",
        ),
        ResolvedToolIdentity(
            logical_name="opensta",
            executable=str(opensta.resolve()),
            version="3.1.0",
            version_output="3.1.0",
            executable_sha256="c" * 64,
            capabilities=["static_timing", "power_estimation", "wire_load_model"],
            identity_kind="local_executable",
        ),
    ]
    monkeypatch.setattr(
        "scripts.prepare_nangate45_ppa_profile.resolve_local_tool_identities",
        lambda **_kwargs: identities,
    )
    profile_path = tmp_path / "profile.yaml"
    manifest_path = tmp_path / "pdk-manifest.json"
    assert (
        prepare_nangate45_profile(
            [
                "--pdk-root",
                str(pdk),
                "--sdc",
                str(sdc),
                "--opensta",
                str(opensta),
                "--output-manifest",
                str(manifest_path),
                "--output-profile",
                str(profile_path),
                "--source",
                "rtl/counter.v",
                "--top",
                "counter",
                "--clock-name",
                "clk",
                "--clock-period",
                "10",
            ]
        )
        == 0
    )
    profile = ToolchainProfileRegistry().load_file(profile_path)
    assert validate_profile(profile).valid
    monkeypatch.setattr(
        "verigym.profiles.resolver.resolve_local_tool_identities",
        lambda **_kwargs: identities,
    )
    resolved = resolve_toolchain_profile(
        profile,
        LocalRuntime(),
        source_paths=["rtl/counter.v"],
        top_module="counter",
        reference_candidate_hash="d" * 64,
    )
    assert resolved.metadata["opensta_executable_sha256"] == "c" * 64

    changed = profile.model_copy(deep=True)
    changed.metadata["opensta_executable_sha256"] = "e" * 64
    with pytest.raises(ConfigurationError, match="OpenSTA executable hash differs"):
        resolve_toolchain_profile(
            changed,
            LocalRuntime(),
            source_paths=["rtl/counter.v"],
            top_module="counter",
            reference_candidate_hash="d" * 64,
        )


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


def test_opensta_script_freezes_wireload_clock_and_activity() -> None:
    request = _opensta_request()
    script = build_opensta_script(request)
    assert "exec yosys -Q -T -l out/yosys.log -s synthesis.ys" in script
    assert "synthesis.ys 2>@1" in script
    assert "set_wire_load_model -name 5K_hvratio_1_1" in script
    assert "set vg_clocks [get_clocks clk]" in script
    assert "set_power_activity -global -activity 0.1 -duty 0.5 -clock $vg_clock" in script
    assert "set vg_slack [get_property $vg_path_end slack]" in script
    assert "report_power -format json -digits 8 > out/power.json" in script
    assert "sta::redirect_file_begin out/units.rpt\nreport_units\n" in script
    assert (
        "sta::redirect_file_begin out/activity_annotation.rpt\n"
        "report_activity_annotation\n" in script
    )
    assert generated_script_hash(request) == generated_script_hash(request.model_copy())


def test_opensta_v1_replay_contract_remains_distinct_from_v2_diagnostics() -> None:
    request = _opensta_request(flow_template_id=LEGACY_FLOW_TEMPLATE_ID)
    script = build_opensta_script(request)
    assert "report_power -format json -digits 8 > out/power.json" in script
    assert "report_units" not in script
    assert "report_activity_annotation" not in script
    assert hash_bytes((LEGACY_FLOW_TEMPLATE_CONTRACT + "\n").encode()) == (
        "3970b2a27fcd92f9cefe950c0741fdc0ead30cca604e273fb38f75b908c7a60b"
    )


def test_opensta_v3_exports_a_parser_compatible_structural_netlist() -> None:
    request = _opensta_request(flow_template_id=COMPATIBILITY_FLOW_TEMPLATE_ID)

    synthesis = build_yosys_script(request)

    assert "write_verilog -noattr -noexpr -nodec -simple-lhs out/netlist.v" in synthesis
    assert "report_units" in build_opensta_script(request)
    assert hash_bytes((COMPATIBILITY_FLOW_TEMPLATE_CONTRACT + "\n").encode()) == (
        "5c02c175d93601b8c153fabe62decfd8213ace994d2f9b496ed872c45304f5ea"
    )
    assert generated_script_hash(request) != generated_script_hash(_opensta_request())


def test_opensta_v4_maps_latches_to_the_frozen_liberty_cells() -> None:
    request = _opensta_request(flow_template_id=LATCH_MAPPING_FLOW_TEMPLATE_ID)

    synthesis = build_yosys_script(request)

    assert "techmap -map profile/latch_map.v" in synthesis
    assert "write_verilog -noattr -noexpr -nodec -simple-lhs out/netlist.v" in synthesis
    assert "$_DLATCH_N_" in LATCH_MAPPING_SOURCE and "DLL_X1" in LATCH_MAPPING_SOURCE
    assert "$_DLATCH_P_" in LATCH_MAPPING_SOURCE and "DLH_X1" in LATCH_MAPPING_SOURCE
    opensta = build_opensta_script(request)
    assert "get_pins -hierarchical */GN" in opensta
    assert "create_clock -name verigym_latch_gate -period 10" in opensta
    assert hash_bytes((LATCH_MAPPING_FLOW_TEMPLATE_CONTRACT + "\n").encode()) != hash_bytes(
        (COMPATIBILITY_FLOW_TEMPLATE_CONTRACT + "\n").encode()
    )


def test_opensta_parsers_require_exact_metrics_and_convert_watts() -> None:
    metrics = parse_opensta_metrics(
        (
            "VERIGYM_OPENSTA_METRICS_V1\n"
            "critical_path_delay=1.25\n"
            "worst_negative_slack=-0.1\n"
            "clock_period=10\n"
            "timing_unit=ns\n"
            f"constraints_sha256={'b' * 64}\n"
            "wire_load_model=5K_hvratio_1_1\n"
            "power_unit=uW\n"
            "power_activity_mode=opensta_global_clock_relative:activity=0.1:duty=0.5\n"
        ).encode()
    )
    assert metrics["critical_path_delay"] == "1.25"
    power = parse_opensta_power_json(
        json.dumps({"Total": {"total": 8.75e-6}}).encode(), target_unit="uW"
    )
    assert power == pytest.approx(8.75)
    with pytest.raises(ValueError, match="fields differ"):
        parse_opensta_metrics(b"VERIGYM_OPENSTA_METRICS_V1\nclock_period=10\n")
    with pytest.raises(ValueError, match="Total"):
        parse_opensta_power_json(b"{}", target_unit="uW")


def test_opensta_request_rejects_implicit_or_incomplete_activity() -> None:
    payload = _opensta_request().model_dump(mode="json")
    payload["power_activity_mode"] = None
    with pytest.raises(ValidationError, match="complete timing/power contract"):
        YosysSynthesisRequest.model_validate(payload)
    payload = _opensta_request().model_dump(mode="json")
    payload["wire_load_model"] = "bad; source /host/file"
    with pytest.raises(ValidationError, match="wire-load"):
        YosysSynthesisRequest.model_validate(payload)


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
