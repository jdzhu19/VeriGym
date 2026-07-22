"""Static profile and asset validation without invoking any external tool."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from pydantic import Field

from verigym.core.hashing import hash_bytes
from verigym.schemas.base import StrictModel
from verigym.schemas.common import ArtifactDescriptor, ToolchainProfile
from verigym.tools.yosys.script_builder import FLOW_TEMPLATE_HASH, FLOW_TEMPLATE_ID


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


def validate_profile(profile: ToolchainProfile) -> ProfileValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if profile.flow is None or profile.metrics is None or profile.reference is None:
        errors.append("profile has no complete synthesis, metric, and reference contract")
        return ProfileValidationResult(valid=False, errors=errors)
    if profile.flow.template_id != FLOW_TEMPLATE_ID:
        errors.append(f"unsupported built-in flow template: {profile.flow.template_id}")
    allowed_runtimes = profile.runtime.allowed_runtimes or [profile.runtime.runtime]
    if "docker" in allowed_runtimes and profile.runtime.network_policy != "none":
        errors.append("Docker synthesis profiles must require network policy 'none'")
    if "docker" not in allowed_runtimes:
        warnings.append("host-local synthesis is exploratory and site-specific only")
    if profile.container_image != profile.runtime.requested_image:
        errors.append("container_image and runtime requested_image must match")
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
    generated_scripts = [
        script
        for script in profile.scripts
        if isinstance(script, ArtifactDescriptor) and script.source_kind == "generated"
    ]
    if len(generated_scripts) != 1:
        errors.append("profile requires exactly one generated flow-template descriptor")
    elif generated_scripts[0].content_hash != FLOW_TEMPLATE_HASH:
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
    if profile.reproducibility_scope == "public" and not profile.runtime.immutable_image_required:
        errors.append("public ranking profiles require an immutable resolved image")
    if profile.reproducibility_scope != "public":
        warnings.append("site-specific/private results are comparable only by resolved hash")
    return ProfileValidationResult(valid=not errors, errors=errors, warnings=warnings)


__all__ = ["ProfileValidationResult", "read_artifact_bytes", "validate_profile"]
