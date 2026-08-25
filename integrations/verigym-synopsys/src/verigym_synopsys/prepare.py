"""Prepare a site-local Design Compiler profile without bundling vendor assets."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

import yaml

from .common import licensed_environment, redact, resolve_executable, safe_executable
from .dc import FLOW_TEMPLATE_HASH, FLOW_TEMPLATE_ID, _probe_dc

_LIBRARY_NAME = re.compile(r'\blibrary\s*\(\s*"?([A-Za-z_][A-Za-z0-9_$]*)"?\s*\)')
_LICENSE_NAMES = {"SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE"}


def _regular_file(value: str) -> Path:
    path = Path(value).expanduser()
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


def _tcl_path(path: Path) -> str:
    value = str(path)
    if any(character in value for character in ("\x00", "\n", "\r", "}")):
        raise ValueError("paths containing NUL, newlines, or '}' are unsupported")
    return "{" + value + "}"


def _convert_liberty(liberty: Path, output: Path, lc_shell: str) -> None:
    text = liberty.read_text(encoding="utf-8", errors="strict")
    match = _LIBRARY_NAME.search(text)
    if match is None:
        raise ValueError("could not identify the Liberty library name")
    library_name = match.group(1)
    output.parent.mkdir(parents=True, exist_ok=True)
    executable = resolve_executable(safe_executable(lc_shell))
    with tempfile.TemporaryDirectory(prefix="verigym-lc-") as temporary_value:
        temporary = Path(temporary_value)
        script = temporary / "convert.tcl"
        script.write_text(
            f"read_lib {_tcl_path(liberty)}\n"
            f"write_lib {library_name} -format db -output {_tcl_path(output)}\n"
            "exit\n",
            encoding="utf-8",
        )
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(temporary),
            "LANG": "C",
            **licensed_environment(),
        }
        completed = subprocess.run(
            [executable, "-no_init", "-no_log", "-f", str(script)],
            cwd=temporary,
            capture_output=True,
            check=False,
            env=environment,
            shell=False,
            text=True,
            timeout=300,
        )
    if completed.returncode != 0 or not output.is_file():
        diagnostic = redact(completed.stdout + "\n" + completed.stderr)[-4000:]
        raise RuntimeError(f"Library Compiler conversion failed:\n{diagnostic}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a Liberty file and emit a site-local VeriGym DC profile."
    )
    parser.add_argument("--liberty", required=True)
    parser.add_argument(
        "--input-db",
        help="Use a prebuilt DB directly; binds it together with --liberty for provenance.",
    )
    parser.add_argument("--sdc", required=True)
    parser.add_argument(
        "--output-db",
        help="DB destination when converting --liberty; omit when --input-db is supplied.",
    )
    parser.add_argument("--output-profile", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--clock-period", type=float, required=True)
    parser.add_argument("--profile-id", default="site-synopsys-dc")
    parser.add_argument("--profile-version", default="1.0.0")
    parser.add_argument("--area-unit", default="um^2")
    parser.add_argument("--timing-unit", default="ns")
    parser.add_argument("--power-unit", choices=["W", "mW", "uW", "nW", "pW"], default="uW")
    parser.add_argument(
        "--power-activity-mode",
        choices=["global_clock_relative"],
        default="global_clock_relative",
        help="Explicit DC switching annotation relative to a named clock.",
    )
    parser.add_argument("--power-activity", type=float, default=0.1)
    parser.add_argument("--power-static-probability", type=float, default=0.5)
    parser.add_argument("--power-base-clock", required=True)
    parser.add_argument("--lc-shell", default=os.environ.get("VERIGYM_LC_EXECUTABLE", "lc_shell"))
    parser.add_argument("--dc-shell", default=os.environ.get("VERIGYM_DC_EXECUTABLE", "dc_shell"))
    parser.add_argument(
        "--license-environment",
        action="append",
        default=[],
        help="Allowed variable name; repeat for SNPSLMD_LICENSE_FILE or LM_LICENSE_FILE.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.clock_period <= 0:
        raise ValueError("--clock-period must be positive")
    if args.power_activity <= 0:
        raise ValueError("--power-activity must be positive")
    if not 0 <= args.power_static_probability <= 1:
        raise ValueError("--power-static-probability must be between zero and one")
    environment_names = sorted(set(args.license_environment))
    unsupported = set(environment_names) - _LICENSE_NAMES
    if unsupported:
        raise ValueError(f"unsupported license environment names: {sorted(unsupported)}")
    missing = [name for name in environment_names if not os.environ.get(name)]
    if missing:
        raise ValueError(f"requested license environment variables are unset: {missing}")
    liberty = _regular_file(args.liberty)
    sdc = _regular_file(args.sdc)
    if args.input_db is not None and args.output_db is not None:
        raise ValueError("--input-db and --output-db are mutually exclusive")
    if args.input_db is None and args.output_db is None:
        raise ValueError("--output-db is required when --input-db is not supplied")
    if args.input_db is not None:
        target_db = _regular_file(args.input_db)
        library_attribution = f"Prebuilt DB paired with {liberty.name}"
    else:
        target_db = Path(args.output_db).expanduser().resolve()
        _convert_liberty(liberty, target_db, args.lc_shell)
        library_attribution = f"Converted locally from {liberty.name}"
    output_profile = Path(args.output_profile).expanduser().resolve()
    dc_executable, dc_version = _probe_dc(args.dc_shell)
    db_hash = _sha256(target_db)
    sdc_hash = _sha256(sdc)
    profile = {
        "id": args.profile_id,
        "version": args.profile_version,
        "description": "Site-local Synopsys DC area/timing/power profile generated by VeriGym.",
        "tools": [
            {
                "name": "design-compiler",
                "executable": dc_executable,
                "version_command": [dc_executable, "-version"],
                "accepted_version": f"=={dc_version}",
                "capabilities": [
                    "synthesis",
                    "mapped_area",
                    "static_timing",
                    "power_estimation",
                ],
            }
        ],
        "runtime": {"runtime": "local", "allowed_runtimes": ["local"]},
        "libraries": [
            {
                "name": "target-db",
                "uri": str(target_db),
                "content_hash": db_hash,
                "license": "user-supplied",
                "media_type": "application/x-synopsys-db",
                "source_kind": "user_path",
                "attribution": library_attribution,
                "redistributable": False,
                "unit": args.area_unit,
                "semantics": "Design Compiler mapped cell area",
                "copy_permitted": True,
            }
        ],
        "constraints": [
            {
                "name": "timing-sdc",
                "uri": str(sdc),
                "content_hash": sdc_hash,
                "license": "user-supplied",
                "media_type": "application/x-sdc",
                "source_kind": "user_path",
                "attribution": "User-supplied benchmark timing constraints",
                "redistributable": False,
                "unit": args.timing_unit,
                "semantics": "Synthesis timing constraints",
                "copy_permitted": True,
            }
        ],
        "scripts": [
            {
                "name": "dc-flow-template",
                "content_hash": FLOW_TEMPLATE_HASH,
                "media_type": "application/x-tcl-template",
                "source_kind": "generated",
                "attribution": "verigym-synopsys",
                "redistributable": True,
                "copy_permitted": True,
            }
        ],
        "environment_allowlist": environment_names,
        "deterministic": True,
        "reproducibility_scope": "site_specific",
        "flow": {
            "frontend": "systemverilog-subset",
            "default_sources": args.source,
            "top_module": args.top,
            "backend_plugin": "synopsys.dc.synth",
            "template_id": FLOW_TEMPLATE_ID,
            "abc_policy_id": "not-applicable",
            "liberty_mapping": True,
            "emit_netlist_verilog": True,
            "emit_netlist_json": False,
            "emit_stat_json": False,
        },
        "metrics": {
            "scope": "synthesis_area_timing_power",
            "area": {
                "enabled": True,
                "source": "design_compiler.mapped_area",
                "unit": args.area_unit,
                "semantics": "Library-relative mapped area",
            },
            "delay": {
                "enabled": True,
                "source": "design_compiler.maximum_timing_path",
                "unit": args.timing_unit,
                "semantics": "Maximum-path arrival time after compile_ultra",
            },
            "worst_negative_slack": {
                "enabled": True,
                "source": "design_compiler.maximum_timing_path",
                "unit": args.timing_unit,
                "semantics": "Minimum of zero and maximum-path slack",
            },
            "power": {
                "enabled": True,
                "source": "design_compiler.report_power.total_dynamic_plus_cell_leakage",
                "unit": args.power_unit,
                "semantics": (
                    "Explicit non-clock primary-input activity; total dynamic plus cell leakage "
                    "power; no placed clock-tree or extracted parasitics"
                ),
            },
            "educational": True,
            "signoff": False,
        },
        "reference": {"strategy": "suite_reference_solution"},
        "metadata": {
            "clock_period": args.clock_period,
            "power_activity_mode": args.power_activity_mode,
            "power_activity": args.power_activity,
            "power_static_probability": args.power_static_probability,
            "power_base_clock": args.power_base_clock,
            "source_liberty_sha256": _sha256(liberty),
        },
    }
    output_profile.parent.mkdir(parents=True, exist_ok=True)
    output_profile.write_text(
        yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(f"wrote site profile: {output_profile}")
    print(f"resolved Design Compiler: {dc_version}")
    print(f"target DB SHA-256: {db_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
