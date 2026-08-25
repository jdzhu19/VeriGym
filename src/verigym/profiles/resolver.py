"""Runtime-aware immutable synthesis-profile resolution."""

from __future__ import annotations

import platform
import re
import tempfile
from pathlib import Path
from typing import Any, Literal, cast

from verigym.core.errors import ConfigurationError, MissingDependencyError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.profiles.base import (
    ResolvedArtifactIdentity,
    ResolvedRuntimeIdentity,
    ResolvedToolchainProfile,
    ResolvedToolIdentity,
)
from verigym.profiles.validation import read_artifact_bytes, validate_yosys_profile
from verigym.runtimes.base import Runtime
from verigym.schemas.common import ArtifactDescriptor, ToolchainProfile
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.tool import CommandSpec, CompletedCommand
from verigym.tools.base import SynthesisBackendPlugin
from verigym.tools.yosys.identity import (
    extract_abc_version,
    extract_yosys_git_hash,
    extract_yosys_version,
    resolve_local_tool_identities,
)
from verigym.tools.yosys.opensta import FLOW_TEMPLATE_IDS as OPENSTA_FLOW_TEMPLATE_IDS
from verigym.tools.yosys.opensta import OpenSTAFlowTemplateId
from verigym.tools.yosys.schemas import YosysSynthesisRequest
from verigym.tools.yosys.script_builder import FLOW_TEMPLATE_ID, generated_script_hash

_SOURCE_IDENTITY = re.compile(
    r"^(Yosys|ABC) vendored source identity:\s*([0-9a-f]{40})$",
    re.MULTILINE,
)


def _runtime_identity(runtime: Runtime) -> ResolvedRuntimeIdentity:
    descriptor = runtime.descriptor
    image = descriptor.image
    security = descriptor.security
    resources = descriptor.resources
    resource_contract = (
        {
            "memory_bytes": resources.memory_bytes,
            "memory_swap_bytes": resources.memory_swap_bytes,
            "swap_enforced": resources.swap_enforced,
            "cpus": resources.cpus,
            "pids_limit": resources.pids_limit,
            "tmpfs_bytes": resources.tmpfs_bytes,
            "stop_timeout_s": resources.stop_timeout_s,
            "max_command_time_s": resources.max_command_time_s,
            "max_artifact_file_bytes": resources.max_artifact_file_bytes,
            "max_artifact_bytes": resources.max_artifact_bytes,
        }
        if resources is not None
        else None
    )
    return ResolvedRuntimeIdentity(
        runtime_slug=descriptor.name,
        isolation_level=descriptor.isolation_level,
        deterministic=descriptor.deterministic,
        os=image.os if image is not None else platform.system().lower(),
        architecture=image.architecture if image is not None else platform.machine(),
        requested_image_reference=(image.requested_reference if image is not None else None),
        resolved_image_id=image.resolved_image_id if image is not None else None,
        configuration_fingerprint=descriptor.configuration_fingerprint,
        network_policy=security.network_mode if security is not None else None,
        resource_controls=(
            resources is not None
            and resources.memory_bytes > 0
            and resources.cpus > 0
            and resources.pids_limit > 0
        ),
        security_hash=content_hash(security) if security is not None else None,
        resource_contract_hash=(
            content_hash(resource_contract) if resource_contract is not None else None
        ),
    )


def _validate_runtime(profile: ToolchainProfile, runtime: Runtime, *, replay: bool) -> None:
    requirement = profile.runtime
    descriptor = runtime.descriptor
    allowed = requirement.allowed_runtimes or [requirement.runtime]
    if descriptor.name not in allowed:
        raise ConfigurationError(
            f"profile {profile.id!r} allows runtimes {allowed}, got {descriptor.name!r}"
        )
    if (
        requirement.minimum_isolation_level is not None
        and descriptor.isolation_level != requirement.minimum_isolation_level
    ):
        raise ConfigurationError(
            f"profile requires isolation {requirement.minimum_isolation_level!r}, "
            f"got {descriptor.isolation_level!r}"
        )
    image = descriptor.image
    if requirement.immutable_image_required and (
        image is None or not image.resolved_image_id.startswith("sha256:")
    ):
        raise ConfigurationError("profile requires an exact immutable Docker image ID")
    if (
        not replay
        and requirement.requested_image is not None
        and (image is None or image.requested_reference != requirement.requested_image)
    ):
        actual = image.requested_reference if image is not None else None
        raise ConfigurationError(
            f"profile requires Docker image reference {requirement.requested_image!r}, "
            f"got {actual!r}"
        )
    if image is not None:
        if requirement.supported_os and image.os not in requirement.supported_os:
            raise ConfigurationError(f"profile does not support image OS {image.os!r}")
        if (
            requirement.supported_architectures
            and image.architecture not in requirement.supported_architectures
        ):
            raise ConfigurationError(
                f"profile does not support image architecture {image.architecture!r}"
            )
    if requirement.network_policy is not None:
        security = descriptor.security
        if security is None or security.network_mode != requirement.network_policy:
            raise ConfigurationError(
                f"profile requires network policy {requirement.network_policy!r}"
            )
    if requirement.resource_controls_required and descriptor.resources is None:
        raise ConfigurationError("profile requires mandatory runtime resource controls")


def _require_command(command: str, completed: CompletedCommand) -> str:
    if completed.error or completed.timed_out or completed.oom_killed:
        raise MissingDependencyError(
            f"profile tool identity command failed before model invocation: {command}"
        )
    if completed.output_truncated or completed.exit_code != 0:
        raise MissingDependencyError(
            f"profile tool identity command returned no usable identity: {command}"
        )
    return (completed.stdout + "\n" + completed.stderr).strip()


def _resolve_docker_tools(runtime: Runtime) -> list[ResolvedToolIdentity]:
    descriptor = runtime.descriptor
    if descriptor.image is None:
        raise ConfigurationError("Docker profile resolution has no immutable image identity")
    with tempfile.TemporaryDirectory(prefix="verigym-profile-probe-") as temporary:
        session = runtime.create_session(
            SessionSpec(
                source_dir=str(Path(temporary)),
                label="diagnostic",
                max_output_bytes=128 * 1024,
            )
        )
        try:
            yosys_result = session.execute(CommandSpec(argv=["yosys", "-V"], timeout_s=15))
            abc_result = session.execute(
                CommandSpec(argv=["yosys-abc", "-c", "version; quit"], timeout_s=15)
            )
            sources_result = session.execute(
                CommandSpec(
                    argv=["verigym-toolchain-identity"],
                    timeout_s=15,
                )
            )
        finally:
            session.close()
    yosys_output = _require_command("yosys -V", yosys_result)
    abc_output = _require_command("yosys-abc version", abc_result)
    source_output = _require_command("open-toolchain source identity", sources_result)
    yosys_version = extract_yosys_version(yosys_output)
    abc_version = extract_abc_version(abc_output)
    if yosys_version is None:
        raise MissingDependencyError("Yosys returned an unsupported version identity")
    if abc_version is None:
        raise MissingDependencyError("ABC returned an unsupported version identity")
    source_identities = {
        name.lower(): value for name, value in _SOURCE_IDENTITY.findall(source_output)
    }
    yosys_git_hash = extract_yosys_git_hash(yosys_output)
    if source_identities.get("yosys") != yosys_git_hash:
        raise ConfigurationError(
            "inside-image Yosys executable and recorded source identities differ"
        )
    abc_git_hash = source_identities.get("abc")
    if abc_git_hash is None:
        raise MissingDependencyError("inside-image ABC source identity is unavailable")
    return [
        ResolvedToolIdentity(
            logical_name="yosys",
            executable="yosys",
            version=yosys_version,
            version_output=yosys_output,
            git_hash=yosys_git_hash,
            capabilities=["synth", "stat_json", "liberty", "abc"],
            identity_kind="immutable_image_observation",
        ),
        ResolvedToolIdentity(
            logical_name="yosys-abc",
            executable="yosys-abc",
            version=abc_version,
            version_output=abc_output,
            git_hash=abc_git_hash,
            capabilities=["liberty_mapping"],
            identity_kind="immutable_image_observation",
        ),
    ]


def _validate_tools(profile: ToolchainProfile, identities: list[ResolvedToolIdentity]) -> None:
    observed = {identity.logical_name: identity for identity in identities}
    for requirement in profile.tools:
        identity = observed.get(requirement.name)
        if identity is None:
            if requirement.required:
                raise MissingDependencyError(
                    f"required profile tool {requirement.name!r} is unavailable"
                )
            continue
        if requirement.executable is not None and identity.executable != requirement.executable:
            raise ConfigurationError(
                f"profile requires executable {requirement.executable!r} for "
                f"{requirement.name!r}, observed {identity.executable!r}"
            )
        missing_capabilities = sorted(set(requirement.capabilities) - set(identity.capabilities))
        if missing_capabilities:
            raise ConfigurationError(
                f"profile tool {requirement.name!r} lacks capabilities: "
                f"{', '.join(missing_capabilities)}"
            )
        if requirement.abc_required and "abc" not in identity.capabilities:
            raise ConfigurationError(f"profile tool {requirement.name!r} lacks required ABC")
        accepted = requirement.accepted_version
        if accepted is not None:
            if not accepted.startswith("=="):
                raise ConfigurationError(f"unsupported built-in version constraint {accepted!r}")
            expected_version = accepted[2:]
            if identity.version != expected_version:
                raise ConfigurationError(
                    f"profile requires {requirement.name} {expected_version}, "
                    f"observed {identity.version}"
                )
        if requirement.git_hash is not None:
            actual = identity.git_hash
            if actual is None or not (
                requirement.git_hash.startswith(actual) or actual.startswith(requirement.git_hash)
            ):
                raise ConfigurationError(
                    f"profile requires {requirement.name} git identity "
                    f"{requirement.git_hash}, observed {actual or 'unavailable'}"
                )


def _resolve_assets(profile: ToolchainProfile) -> list[ResolvedArtifactIdentity]:
    resolved: list[ResolvedArtifactIdentity] = []
    descriptors = [*profile.libraries]
    if profile.pdk is not None:
        descriptors.append(profile.pdk)
    descriptors.extend(
        script for script in profile.scripts if isinstance(script, ArtifactDescriptor)
    )
    descriptors.extend(
        constraint
        for constraint in profile.constraints
        if isinstance(constraint, ArtifactDescriptor)
    )
    for descriptor in descriptors:
        if descriptor.content_hash is None or descriptor.source_kind is None:
            raise ConfigurationError(
                f"comparison-relevant artifact {descriptor.name!r} lacks an immutable identity"
            )
        if descriptor.source_kind == "generated":
            actual_hash = descriptor.content_hash
        else:
            try:
                actual_hash = hash_bytes(read_artifact_bytes(descriptor))
            except Exception as exc:
                raise ConfigurationError(str(exc)) from exc
        if actual_hash != descriptor.content_hash:
            raise ConfigurationError(f"artifact hash mismatch for {descriptor.name!r}")
        resolved.append(
            ResolvedArtifactIdentity(
                logical_id=descriptor.name,
                media_type=descriptor.media_type or "application/octet-stream",
                source_kind=descriptor.source_kind,
                content_hash=actual_hash,
                license=descriptor.license,
                attribution=descriptor.attribution,
                redistributable=descriptor.redistributable is True,
                unit=descriptor.unit,
                semantics=descriptor.semantics,
                copy_permitted=descriptor.copy_permitted,
                replay_locator=descriptor.uri,
            )
        )
    return sorted(resolved, key=lambda item: item.logical_id)


def resolve_yosys_toolchain_profile(
    profile: ToolchainProfile,
    runtime: Runtime,
    *,
    source_paths: list[str],
    top_module: str,
    reference_candidate_hash: str | None,
    expected: ResolvedToolchainProfile | None = None,
) -> ResolvedToolchainProfile:
    validation = validate_yosys_profile(profile)
    if not validation.valid:
        raise ConfigurationError("; ".join(validation.errors))
    assert profile.flow is not None
    assert profile.metrics is not None
    assert profile.reference is not None
    if source_paths != profile.flow.default_sources:
        raise ConfigurationError(
            "task synthesis sources do not match the profile's deterministic source contract"
        )
    if top_module != profile.flow.top_module:
        raise ConfigurationError("task top module does not match the profile contract")
    replay = expected is not None
    _validate_runtime(profile, runtime, replay=replay)
    runtime_identity = _runtime_identity(runtime)
    opensta_flow = profile.flow.template_id in OPENSTA_FLOW_TEMPLATE_IDS
    opensta_executable = None
    if opensta_flow:
        opensta_requirement = next(
            (requirement for requirement in profile.tools if requirement.name == "opensta"), None
        )
        if opensta_requirement is None or opensta_requirement.executable is None:
            raise ConfigurationError("Yosys/OpenSTA profile has no OpenSTA executable")
        opensta_executable = opensta_requirement.executable
    if expected is not None:
        if expected.profile_id != profile.id or expected.profile_version != profile.version:
            raise ConfigurationError("stored resolved profile does not match the declared profile")
        if runtime_identity.resolved_image_id != expected.runtime_identity.resolved_image_id:
            raise ConfigurationError("exact resolved profile image is unavailable for replay")
        if runtime_identity.runtime_slug == "docker":
            tool_identities = [item.model_copy(deep=True) for item in expected.tool_identities]
        else:
            tool_identities = (
                resolve_local_tool_identities(opensta_executable=opensta_executable)
                if opensta_executable is not None
                else resolve_local_tool_identities()
            )
    elif runtime_identity.runtime_slug == "docker":
        tool_identities = _resolve_docker_tools(runtime)
    else:
        tool_identities = (
            resolve_local_tool_identities(opensta_executable=opensta_executable)
            if opensta_executable is not None
            else resolve_local_tool_identities()
        )
    _validate_tools(profile, tool_identities)
    assets = _resolve_assets(profile)
    liberty = next(
        (asset for asset in assets if asset.media_type == "application/x-liberty"),
        None,
    )
    if liberty is None or liberty.unit is None:
        raise ConfigurationError("resolved profile has no usable Liberty area asset")
    yosys_identity = next(
        identity for identity in tool_identities if identity.logical_name == "yosys"
    )
    if opensta_flow:
        constraint = next(asset for asset in assets if asset.media_type == "application/x-sdc")
        opensta_identity = next(
            identity for identity in tool_identities if identity.logical_name == "opensta"
        )
        if opensta_identity.executable_sha256 != profile.metadata["opensta_executable_sha256"]:
            raise ConfigurationError("OpenSTA executable hash differs from the declared profile")
        script_request = YosysSynthesisRequest(
            sources=source_paths,
            top=top_module,
            frontend=profile.flow.frontend,
            flatten=profile.flow.flatten,
            liberty_asset_id=liberty.logical_id,
            liberty_path=".verigym_profile/cells.lib",
            liberty_sha256=liberty.content_hash,
            area_unit=liberty.unit,
            flow_template_id=cast(OpenSTAFlowTemplateId, profile.flow.template_id),
            emit_netlist_verilog=profile.flow.emit_netlist_verilog,
            emit_netlist_json=profile.flow.emit_netlist_json,
            emit_stat_json=profile.flow.emit_stat_json,
            require_mapped_area=profile.metrics.area.enabled,
            constraints_path=".verigym_profile/constraints.sdc",
            constraints_sha256=constraint.content_hash,
            timing_unit=constraint.unit,
            power_unit=cast(Literal["W", "mW", "uW", "nW", "pW"], profile.metrics.power.unit),
            clock_name=str(profile.metadata["clock_name"]),
            clock_period=float(profile.metadata["clock_period"]),
            wire_load_model=str(profile.metadata["wire_load_model"]),
            power_activity_mode="global_clock_relative",
            power_activity=float(profile.metadata["power_activity"]),
            power_duty=float(profile.metadata["power_duty"]),
            opensta_executable=opensta_identity.executable,
            opensta_executable_sha256=opensta_identity.executable_sha256,
            expected_opensta_version=opensta_identity.version,
            expected_yosys_version=yosys_identity.version,
        )
    else:
        script_request = YosysSynthesisRequest(
            sources=source_paths,
            top=top_module,
            frontend=profile.flow.frontend,
            flatten=profile.flow.flatten,
            liberty_asset_id=liberty.logical_id,
            liberty_path=".verigym_profile/cells.lib",
            liberty_sha256=liberty.content_hash,
            area_unit=liberty.unit,
            flow_template_id=FLOW_TEMPLATE_ID,
            emit_netlist_verilog=profile.flow.emit_netlist_verilog,
            emit_netlist_json=profile.flow.emit_netlist_json,
            emit_stat_json=profile.flow.emit_stat_json,
            require_mapped_area=profile.metrics.area.enabled,
            expected_yosys_version=yosys_identity.version,
        )
    unresolved = ResolvedToolchainProfile(
        profile_id=profile.id,
        profile_version=profile.version,
        declared_profile_hash=content_hash(profile),
        resolved_profile_hash="",
        reproducibility_scope=profile.reproducibility_scope,
        deterministic=profile.deterministic,
        runtime_identity=runtime_identity,
        tool_identities=sorted(tool_identities, key=lambda item: item.logical_name),
        asset_identities=assets,
        flow_hash=content_hash(profile.flow),
        metric_contract_hash=content_hash(profile.metrics),
        reference_contract_hash=content_hash(profile.reference),
        flow_template_id=profile.flow.template_id,
        generated_script_hash=generated_script_hash(script_request),
        top_module=top_module,
        source_paths=source_paths,
        metric_scope=profile.metrics.scope,
        area_unit=liberty.unit,
        timing_unit=(constraint.unit if opensta_flow else None),
        power_unit=(profile.metrics.power.unit if opensta_flow else None),
        reference_strategy=profile.reference.strategy,
        reference_candidate_hash=reference_candidate_hash,
        metadata={
            "liberty_asset_id": liberty.logical_id,
            "liberty_sha256": liberty.content_hash,
            "flow_template_hash": next(
                (
                    asset.content_hash
                    for asset in assets
                    if asset.media_type == "application/x-yosys-script-template"
                ),
                None,
            ),
            **(
                {
                    "constraints_sha256": constraint.content_hash,
                    "clock_name": profile.metadata["clock_name"],
                    "clock_period": profile.metadata["clock_period"],
                    "wire_load_model": profile.metadata["wire_load_model"],
                    "power_activity_mode": profile.metadata["power_activity_mode"],
                    "power_activity": profile.metadata["power_activity"],
                    "power_duty": profile.metadata["power_duty"],
                    "opensta_executable_sha256": profile.metadata["opensta_executable_sha256"],
                    "pdk_tree_sha256": profile.metadata["pdk_tree_sha256"],
                }
                if opensta_flow
                else {}
            ),
        },
    )
    resolved_hash = content_hash(unresolved.identity_payload())
    resolved = unresolved.model_copy(update={"resolved_profile_hash": resolved_hash})
    if expected is not None and resolved.resolved_profile_hash != expected.resolved_profile_hash:
        raise ConfigurationError(
            "resolved toolchain profile differs from the exact stored replay profile"
        )
    return resolved


def resolve_toolchain_profile(
    profile: ToolchainProfile,
    runtime: Runtime,
    *,
    source_paths: list[str],
    top_module: str,
    reference_candidate_hash: str | None,
    expected: ResolvedToolchainProfile | None = None,
    backend: SynthesisBackendPlugin | None = None,
) -> ResolvedToolchainProfile:
    """Resolve through an installed backend, defaulting to the built-in Yosys flow."""

    if backend is not None:
        return backend.resolve_profile(
            profile,
            runtime,
            source_paths=source_paths,
            top_module=top_module,
            reference_candidate_hash=reference_candidate_hash,
            expected=expected,
        )
    if profile.flow is not None and profile.flow.backend_plugin != "yosys.synth":
        raise ConfigurationError(
            f"profile backend {profile.flow.backend_plugin!r} was not supplied for resolution"
        )
    return resolve_yosys_toolchain_profile(
        profile,
        runtime,
        source_paths=source_paths,
        top_module=top_module,
        reference_candidate_hash=reference_candidate_hash,
        expected=expected,
    )


def synthesis_request_from_profile(
    profile: ToolchainProfile,
    resolved: ResolvedToolchainProfile,
    *,
    run_label: Literal["candidate", "reference"],
) -> dict[str, Any]:
    assert profile.flow is not None and profile.metrics is not None
    liberty = next(
        asset for asset in resolved.asset_identities if asset.media_type == "application/x-liberty"
    )
    yosys = next(tool for tool in resolved.tool_identities if tool.logical_name == "yosys")
    opensta_flow = profile.flow.template_id in OPENSTA_FLOW_TEMPLATE_IDS
    tool_identity: dict[str, str | None] = {
        "yosys_version": yosys.version,
        "yosys_git_hash": yosys.git_hash,
        "runtime_image_id": resolved.runtime_identity.resolved_image_id,
    }
    common: dict[str, Any] = dict(
        sources=resolved.source_paths,
        top=resolved.top_module,
        frontend=profile.flow.frontend,
        flatten=profile.flow.flatten,
        liberty_asset_id=liberty.logical_id,
        liberty_path=".verigym_profile/cells.lib",
        liberty_sha256=liberty.content_hash,
        area_unit=liberty.unit,
        emit_netlist_verilog=profile.flow.emit_netlist_verilog,
        emit_netlist_json=profile.flow.emit_netlist_json,
        emit_stat_json=profile.flow.emit_stat_json,
        require_mapped_area=profile.metrics.area.enabled,
        expected_yosys_version=yosys.version,
        resolved_profile_hash=resolved.resolved_profile_hash,
        tool_identity=tool_identity,
    )
    if opensta_flow:
        constraint = next(
            asset for asset in resolved.asset_identities if asset.media_type == "application/x-sdc"
        )
        opensta = next(tool for tool in resolved.tool_identities if tool.logical_name == "opensta")
        opensta_common = {
            **common,
            "tool_identity": {
                **tool_identity,
                "opensta_version": opensta.version,
                "opensta_executable_sha256": opensta.executable_sha256,
            },
        }
        request = YosysSynthesisRequest.model_validate(
            {
                **opensta_common,
                "flow_template_id": profile.flow.template_id,
                "constraints_path": ".verigym_profile/constraints.sdc",
                "constraints_sha256": constraint.content_hash,
                "timing_unit": resolved.timing_unit,
                "power_unit": resolved.power_unit,
                "clock_name": str(resolved.metadata["clock_name"]),
                "clock_period": float(resolved.metadata["clock_period"]),
                "wire_load_model": str(resolved.metadata["wire_load_model"]),
                "power_activity_mode": "global_clock_relative",
                "power_activity": float(resolved.metadata["power_activity"]),
                "power_duty": float(resolved.metadata["power_duty"]),
                "opensta_executable": opensta.executable,
                "opensta_executable_sha256": opensta.executable_sha256,
                "expected_opensta_version": opensta.version,
                "expected_flow_script_hash": resolved.generated_script_hash,
                "run_label": run_label,
            }
        )
    else:
        request = YosysSynthesisRequest.model_validate(
            {
                **common,
                "flow_template_id": FLOW_TEMPLATE_ID,
                "expected_flow_script_hash": resolved.generated_script_hash,
                "run_label": run_label,
            }
        )
    return request.model_dump(mode="json")


__all__ = [
    "resolve_toolchain_profile",
    "resolve_yosys_toolchain_profile",
    "synthesis_request_from_profile",
]
