#!/usr/bin/env python3
"""Freeze a Nangate45 tree and emit a site-specific Yosys/OpenSTA PPA profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from verigym.core.hashing import hash_bytes
from verigym.schemas.common import ToolchainProfile
from verigym.tools.yosys.identity import resolve_local_tool_identities
from verigym.tools.yosys.opensta import FLOW_TEMPLATE_CONTRACT, FLOW_TEMPLATE_ID

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_LIBERTY_RELATIVE = Path("Front_End/Liberty/NLDM/NangateOpenCellLibrary_typical.lib")


def _regular_file(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError(f"input cannot be a symlink: {path}")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"input is not a regular file: {path}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def build_pdk_manifest(pdk_root: Path) -> dict[str, Any]:
    root = pdk_root.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("PDK root must be a real directory, not a symlink")
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"PDK manifest refuses symlink: {path.relative_to(root)}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        files.append({"path": relative, "sha256": _sha256(path), "size_bytes": size})
        total_bytes += size
    if not files:
        raise ValueError("PDK root contains no files")
    tree_payload = {"files": files}
    return {
        "schema": "verigym.pdk-manifest.v1",
        "name": "NangateOpenCellLibrary",
        "version": "PDKv1_3_v2010_12",
        "process_label": "45nm",
        "file_count": len(files),
        "total_bytes": total_bytes,
        "tree_sha256": hash_bytes(_canonical_json(tree_payload)),
        "files": files,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hash a Nangate45 PDK tree and emit a Yosys/OpenSTA site profile."
    )
    parser.add_argument("--pdk-root", required=True)
    parser.add_argument("--sdc", required=True)
    parser.add_argument("--opensta", required=True)
    parser.add_argument("--output-manifest", required=True)
    parser.add_argument("--output-profile", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--clock-name", required=True)
    parser.add_argument("--clock-period", type=float, required=True)
    parser.add_argument("--wire-load-model", default="5K_hvratio_1_1")
    parser.add_argument("--power-activity", type=float, default=0.1)
    parser.add_argument("--power-duty", type=float, default=0.5)
    parser.add_argument("--profile-id", default="site-nangate45-yosys-opensta-atp-v2")
    parser.add_argument("--profile-version", default="2.0.0")
    parser.add_argument("--area-unit", default="um^2")
    parser.add_argument("--timing-unit", default="ns")
    parser.add_argument("--power-unit", choices=["W", "mW", "uW", "nW", "pW"], default="uW")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.clock_period <= 0 or args.power_activity <= 0:
        raise ValueError("clock period and power activity must be positive")
    if not 0 <= args.power_duty <= 1:
        raise ValueError("power duty must be between zero and one")
    if _IDENTIFIER.fullmatch(args.top) is None or _IDENTIFIER.fullmatch(args.clock_name) is None:
        raise ValueError("top and clock names must be ordinary Verilog identifiers")
    if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", args.wire_load_model) is None:
        raise ValueError("wire-load model contains unsupported characters")

    pdk_root = Path(args.pdk_root).expanduser().resolve(strict=True)
    liberty = _regular_file(pdk_root / _LIBERTY_RELATIVE)
    sdc = _regular_file(Path(args.sdc).expanduser())
    opensta = _regular_file(Path(args.opensta).expanduser())
    output_manifest = Path(args.output_manifest).expanduser().resolve()
    output_profile = Path(args.output_profile).expanduser().resolve()
    if output_manifest.is_relative_to(pdk_root) or output_profile.is_relative_to(pdk_root):
        raise ValueError("generated identity files must be outside the frozen PDK tree")

    manifest = build_pdk_manifest(pdk_root)
    manifest_payload = _canonical_json(manifest)
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_bytes(manifest_payload)

    identities = resolve_local_tool_identities(opensta_executable=str(opensta))
    tools = {identity.logical_name: identity for identity in identities}
    yosys = tools["yosys"]
    abc = tools["yosys-abc"]
    sta = tools["opensta"]
    template_hash = hash_bytes((FLOW_TEMPLATE_CONTRACT + "\n").encode("utf-8"))
    profile_payload: dict[str, Any] = {
        "id": args.profile_id,
        "version": args.profile_version,
        "description": (
            "Site-specific Nangate45 synthesis area/timing/power profile using Yosys/ABC "
            "and standalone OpenSTA; vectorless and non-signoff."
        ),
        "reproducibility_scope": "site_specific",
        "deterministic": True,
        "runtime": {"runtime": "local", "allowed_runtimes": ["local"]},
        "pdk": {
            "name": "nangate45-pdk-tree-manifest",
            "uri": str(output_manifest),
            "content_hash": hash_bytes(manifest_payload),
            "version": "PDKv1_3_v2010_12",
            "license": "Apache-2.0",
            "media_type": "application/vnd.verigym.pdk-manifest+json",
            "source_kind": "user_path",
            "attribution": "Nangate/Silvaco 45nm Open Cell Library contribution to Si2",
            "redistributable": True,
            "semantics": "Full-tree file/size/SHA-256 manifest; PDK bytes are not bundled",
            "copy_permitted": False,
        },
        "tools": [
            {
                "name": "yosys",
                "executable": "yosys",
                "version": yosys.version,
                "accepted_version": f"=={yosys.version}",
                "version_command": ["yosys", "-V"],
                "capabilities": ["synth", "stat_json", "liberty", "abc"],
                "abc_required": True,
            },
            {
                "name": "yosys-abc",
                "executable": "yosys-abc",
                "version": abc.version,
                "accepted_version": f"=={abc.version}",
                "version_command": ["yosys-abc", "-c", "version; quit"],
                "capabilities": ["liberty_mapping"],
            },
            {
                "name": "opensta",
                "executable": sta.executable,
                "version": sta.version,
                "accepted_version": f"=={sta.version}",
                "version_command": [sta.executable, "-version"],
                "capabilities": [
                    "static_timing",
                    "power_estimation",
                    "wire_load_model",
                ],
            },
        ],
        "libraries": [
            {
                "name": "nangate45-typical-nldm",
                "uri": str(liberty),
                "content_hash": _sha256(liberty),
                "version": "PDKv1_3_v2010_12",
                "license": "Apache-2.0",
                "media_type": "application/x-liberty",
                "source_kind": "user_path",
                "attribution": "Nangate/Silvaco Open Cell Library, typical NLDM corner",
                "redistributable": True,
                "unit": args.area_unit,
                "semantics": "Nangate45 typical 1.10 V, 25 C mapped standard-cell area",
                "copy_permitted": True,
            }
        ],
        "constraints": [
            {
                "name": "timing-sdc",
                "uri": str(sdc),
                "content_hash": _sha256(sdc),
                "license": "user-supplied",
                "media_type": "application/x-sdc",
                "source_kind": "user_path",
                "attribution": "User-supplied benchmark timing constraints",
                "redistributable": False,
                "unit": args.timing_unit,
                "semantics": "Synthesis-level timing constraints",
                "copy_permitted": True,
            }
        ],
        "scripts": [
            {
                "name": FLOW_TEMPLATE_ID,
                "content_hash": template_hash,
                "version": "2.0.0",
                "license": "Apache-2.0",
                "media_type": "application/x-yosys-script-template",
                "source_kind": "generated",
                "attribution": "VeriGym contributors",
                "redistributable": True,
                "semantics": (
                    "Trusted deterministic Yosys plus standalone OpenSTA template with "
                    "unit and activity-annotation diagnostics"
                ),
                "copy_permitted": True,
            }
        ],
        "flow": {
            "frontend": "systemverilog-subset",
            "default_sources": args.source,
            "top_module": args.top,
            "backend_plugin": "yosys.synth",
            "template_id": FLOW_TEMPLATE_ID,
            "abc_policy_id": "verigym-abc-liberty-v1",
            "liberty_mapping": True,
            "emit_netlist_verilog": True,
            "emit_netlist_json": True,
            "emit_stat_json": True,
        },
        "metrics": {
            "scope": "synthesis_area_timing_power",
            "area": {
                "enabled": True,
                "source": "yosys.stat_json.liberty_area",
                "unit": args.area_unit,
                "semantics": "Liberty-mapped cell area before physical design",
            },
            "delay": {
                "enabled": True,
                "source": "opensta.maximum_path.arrival",
                "unit": args.timing_unit,
                "semantics": "Maximum-path arrival with the explicit Liberty wire-load model",
            },
            "worst_negative_slack": {
                "enabled": True,
                "source": "opensta.maximum_path.slack",
                "unit": args.timing_unit,
                "semantics": "Minimum of zero and maximum-path slack",
            },
            "power": {
                "enabled": True,
                "source": "opensta.report_power.json.Total.total",
                "unit": args.power_unit,
                "semantics": (
                    "Vectorless total internal, switching, and leakage power with explicit "
                    "global clock-relative activity; no placement, CTS, routing, or SPEF"
                ),
            },
            "educational": True,
            "signoff": False,
        },
        "reference": {"strategy": "suite_reference_solution"},
        "environment_allowlist": [],
        "metadata": {
            "clock_name": args.clock_name,
            "clock_period": args.clock_period,
            "wire_load_model": args.wire_load_model,
            "power_activity_mode": "global_clock_relative",
            "power_activity": args.power_activity,
            "power_duty": args.power_duty,
            "pdk_tree_sha256": manifest["tree_sha256"],
            "opensta_executable_sha256": sta.executable_sha256,
            "scope_label": "synthesis-area-timing-power-vectorless-non-signoff",
        },
    }
    profile = ToolchainProfile.model_validate(profile_payload)
    output_profile.parent.mkdir(parents=True, exist_ok=True)
    output_profile.write_text(
        yaml.safe_dump(profile.model_dump(mode="json", exclude_none=True), sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote PDK manifest: {output_manifest}")
    print(f"PDK tree SHA-256: {manifest['tree_sha256']}")
    print(f"wrote site profile: {output_profile}")
    print(f"OpenSTA: {sta.version} ({sta.executable_sha256})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
