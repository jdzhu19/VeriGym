"""Static profile and asset validation without invoking any external tool."""

from __future__ import annotations

import math
import re
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field

from verigym.core.hashing import hash_bytes
from verigym.schemas.base import StrictModel
from verigym.schemas.common import ArtifactDescriptor, ToolchainProfile
from verigym.tools.yosys.opensta import (
    FLOW_TEMPLATE_CONTRACTS as OPENSTA_FLOW_TEMPLATE_CONTRACTS,
)
from verigym.tools.yosys.opensta import (
    FLOW_TEMPLATE_IDS as OPENSTA_FLOW_TEMPLATE_IDS,
)
from verigym.tools.yosys.script_builder import FLOW_TEMPLATE_HASH, FLOW_TEMPLATE_ID

if TYPE_CHECKING:
    from verigym.tools.base import SynthesisBackendPlugin


class ProfileValidationResult(StrictModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def read_artifact_bytes(descriptor: ArtifactDescriptor) -> bytes:
    if descriptor.source_kind == "package_resource":
        if descriptor.uri is None or ":" not in descriptor.uri:
            raise ValueError(f"package asset {descriptor.name!r} has no package-resource URI")
        package, relative = descriptor.uri.split(":", 1)
        if not package or not relative or ".." in Path(relative).parts:
            raise ValueError(f"package asset {descriptor.name!r} has an unsafe resource path")
        resource = files(package).joinpath(relative)
        resource_path = Path(str(resource))
        if resource_path.is_symlink():
            raise ValueError(f"package asset {descriptor.name!r} cannot be a symlink")
        return resource.read_bytes()
    if descriptor.source_kind == "user_path":
        if descriptor.uri is None:
            raise ValueError(f"private asset {descriptor.name!r} has no re-resolution path")
        path = Path(descriptor.uri).expanduser()
        if path.is_symlink():
            raise ValueError(f"private asset {descriptor.name!r} cannot be a symlink")
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError(f"private asset {descriptor.name!r} is not a regular file")
        return resolved.read_bytes()
    raise ValueError(f"artifact {descriptor.name!r} is not a readable external asset")


def validate_yosys_profile(profile: ToolchainProfile) -> ProfileValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if profile.flow is None or profile.metrics is None or profile.reference is None:
        errors.append("profile has no complete synthesis, metric, and reference contract")
        return ProfileValidationResult(valid=False, errors=errors)
    opensta_flow = profile.flow.template_id in OPENSTA_FLOW_TEMPLATE_IDS
    if profile.flow.template_id not in {FLOW_TEMPLATE_ID, *OPENSTA_FLOW_TEMPLATE_IDS}:
        errors.append(f"unsupported built-in flow template: {profile.flow.template_id}")
    expected_scope = "synthesis_area_timing_power" if opensta_flow else "synthesis_area_only"
    if profile.metrics.scope != expected_scope:
        errors.append(
            f"flow template {profile.flow.template_id!r} requires metric scope {expected_scope!r}"
        )
    allowed_runtimes = profile.runtime.allowed_runtimes or [profile.runtime.runtime]
    if "docker" in allowed_runtimes and profile.runtime.network_policy != "none":
        errors.append("Docker synthesis profiles must require network policy 'none'")
    if "docker" not in allowed_runtimes:
        warnings.append("host-local synthesis is exploratory and site-specific only")
    if profile.container_image != profile.runtime.requested_image:
        errors.append("container_image and runtime requested_image must match")
    if opensta_flow:
        if allowed_runtimes != ["local"]:
            errors.append("the initial site-specific Yosys/OpenSTA flow requires local runtime")
        if profile.reproducibility_scope == "public":
            errors.append("host-local Yosys/OpenSTA profiles cannot claim public reproducibility")
    if profile.metrics.area.enabled:
        liberty_assets = [
            asset for asset in profile.libraries if asset.media_type == "application/x-liberty"
        ]
        if len(liberty_assets) != 1:
            errors.append("mapped area requires exactly one Liberty artifact")
        for asset in liberty_assets:
            if asset.content_hash is None:
                errors.append(f"Liberty artifact {asset.name!r} has no SHA-256 identity")
                continue
            try:
                actual = hash_bytes(read_artifact_bytes(asset))
            except Exception as exc:
                errors.append(str(exc))
                continue
            if actual != asset.content_hash:
                errors.append(f"Liberty artifact hash mismatch for {asset.name!r}")
            if asset.unit != profile.metrics.area.unit:
                errors.append("Liberty unit and mapped-area metric unit differ")
            if not asset.license or not asset.attribution:
                errors.append("redistributed Liberty assets require license and attribution")
            if asset.redistributable is not True:
                errors.append("the built-in Liberty asset must be explicitly redistributable")
    if opensta_flow:
        if profile.metrics.delay.unit != profile.metrics.worst_negative_slack.unit:
            errors.append("OpenSTA delay and worst-negative-slack units must match")
        if profile.metrics.power.unit not in {"W", "mW", "uW", "nW", "pW"}:
            errors.append("OpenSTA power requires a supported explicit unit")
        constraints = [
            item
            for item in profile.constraints
            if isinstance(item, ArtifactDescriptor) and item.media_type == "application/x-sdc"
        ]
        if len(constraints) != 1:
            errors.append("Yosys/OpenSTA profiles require exactly one SDC artifact")
        for constraint in constraints:
            if constraint.content_hash is None:
                errors.append(f"SDC artifact {constraint.name!r} has no SHA-256 identity")
                continue
            try:
                actual = hash_bytes(read_artifact_bytes(constraint))
            except Exception as exc:
                errors.append(str(exc))
                continue
            if actual != constraint.content_hash:
                errors.append(f"SDC artifact hash mismatch for {constraint.name!r}")
            if constraint.copy_permitted is not True:
                errors.append("SDC artifact is not approved for verifier-private staging")
            if constraint.unit != profile.metrics.delay.unit:
                errors.append("SDC unit and timing metric unit differ")
    generated_scripts = [
        script
        for script in profile.scripts
        if isinstance(script, ArtifactDescriptor) and script.source_kind == "generated"
    ]
    if len(generated_scripts) != 1:
        errors.append("profile requires exactly one generated flow-template descriptor")
    expected_template_hash = FLOW_TEMPLATE_HASH
    if opensta_flow:
        expected_template_hash = hash_bytes(
            (OPENSTA_FLOW_TEMPLATE_CONTRACTS[profile.flow.template_id] + "\n").encode("utf-8")
        )
    if len(generated_scripts) == 1 and generated_scripts[0].content_hash != expected_template_hash:
        errors.append("generated flow-template hash does not match the implementation")
    tool_names = {tool.name for tool in profile.tools}
    if "yosys" not in tool_names or "yosys-abc" not in tool_names:
        errors.append("profile must declare both Yosys and ABC identities")
    else:
        tools = {tool.name: tool for tool in profile.tools}
        yosys = tools["yosys"]
        abc = tools["yosys-abc"]
        if yosys.executable != "yosys" or yosys.version_command != ["yosys", "-V"]:
            errors.append("canonical Yosys executable/version command contract changed")
        if not yosys.abc_required:
            errors.append("canonical Yosys flow must require ABC")
        missing_yosys = sorted({"synth", "stat_json", "liberty", "abc"} - set(yosys.capabilities))
        if missing_yosys:
            errors.append(
                "canonical Yosys capability contract is incomplete: " + ", ".join(missing_yosys)
            )
        if abc.executable != "yosys-abc" or abc.version_command != [
            "yosys-abc",
            "-c",
            "version; quit",
        ]:
            errors.append("canonical ABC executable/version command contract changed")
        if "liberty_mapping" not in abc.capabilities:
            errors.append("canonical ABC capability contract is incomplete")
    if opensta_flow:
        opensta_tools = [tool for tool in profile.tools if tool.name == "opensta"]
        if len(opensta_tools) != 1 or opensta_tools[0].executable is None:
            errors.append("Yosys/OpenSTA profiles require one OpenSTA executable identity")
        else:
            missing_opensta = {
                "static_timing",
                "power_estimation",
                "wire_load_model",
            } - set(opensta_tools[0].capabilities)
            if missing_opensta:
                errors.append("OpenSTA capability contract is incomplete")
        clock_name = profile.metadata.get("clock_name")
        if (
            not isinstance(clock_name, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", clock_name) is None
        ):
            errors.append("Yosys/OpenSTA metadata 'clock_name' is missing or invalid")
        wire_load_model = profile.metadata.get("wire_load_model")
        if (
            not isinstance(wire_load_model, str)
            or re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", wire_load_model) is None
        ):
            errors.append("Yosys/OpenSTA metadata 'wire_load_model' is missing or invalid")
        if not isinstance(profile.metadata.get("power_activity_mode"), str):
            errors.append("Yosys/OpenSTA metadata 'power_activity_mode' is missing or invalid")
        for name in ("clock_period", "power_activity", "power_duty"):
            value = profile.metadata.get(name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
            ):
                errors.append(f"Yosys/OpenSTA metadata {name!r} is missing or invalid")
        if profile.metadata.get("power_activity_mode") != "global_clock_relative":
            errors.append("Yosys/OpenSTA power activity mode is unsupported")
        for name in ("clock_period", "power_activity"):
            value = profile.metadata.get(name)
            if isinstance(value, (int, float)) and float(value) <= 0:
                errors.append(f"Yosys/OpenSTA metadata {name!r} must be positive")
        duty = profile.metadata.get("power_duty")
        if isinstance(duty, (int, float)) and not 0 <= float(duty) <= 1:
            errors.append("Yosys/OpenSTA power duty must be between zero and one")
        opensta_hash = profile.metadata.get("opensta_executable_sha256")
        if not isinstance(opensta_hash, str) or re.fullmatch(r"[0-9a-f]{64}", opensta_hash) is None:
            errors.append("Yosys/OpenSTA metadata has no valid OpenSTA executable hash")
        pdk_tree_hash = profile.metadata.get("pdk_tree_sha256")
        if (
            not isinstance(pdk_tree_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", pdk_tree_hash) is None
        ):
            errors.append("Yosys/OpenSTA metadata has no valid PDK tree hash")
        if profile.pdk is None:
            errors.append("Yosys/OpenSTA profiles require a hashed PDK manifest")
        elif profile.pdk.content_hash is None:
            errors.append("PDK manifest has no SHA-256 identity")
        else:
            try:
                actual = hash_bytes(read_artifact_bytes(profile.pdk))
            except Exception as exc:
                errors.append(str(exc))
            else:
                if actual != profile.pdk.content_hash:
                    errors.append("PDK manifest hash mismatch")
    if profile.reproducibility_scope == "public" and not profile.runtime.immutable_image_required:
        errors.append("public ranking profiles require an immutable resolved image")
    if profile.reproducibility_scope != "public":
        warnings.append("site-specific/private results are comparable only by resolved hash")
    return ProfileValidationResult(valid=not errors, errors=errors, warnings=warnings)


def validate_profile(
    profile: ToolchainProfile,
    backend: SynthesisBackendPlugin | None = None,
) -> ProfileValidationResult:
    """Validate through the selected backend while preserving the Yosys default."""

    if backend is not None:
        result = backend.validate_profile_contract(profile)
        if not isinstance(result, ProfileValidationResult):
            raise TypeError("synthesis backend returned an invalid profile validation result")
        return result
    if profile.flow is None or profile.flow.backend_plugin == "yosys.synth":
        return validate_yosys_profile(profile)
    return ProfileValidationResult(
        valid=False,
        errors=[
            f"profile backend {profile.flow.backend_plugin!r} must be installed for validation"
        ],
    )


__all__ = [
    "ProfileValidationResult",
    "read_artifact_bytes",
    "validate_profile",
    "validate_yosys_profile",
]
