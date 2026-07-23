"""Execute and assemble the local Milestones 0–9 release-candidate audit."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from verigym.core.hashing import hash_directory
from verigym.provenance import get_build_provenance
from verigym.release_audit import (
    evaluate_gate,
    sha256_file,
    validate_bundle,
    write_hash_manifest,
)
from verigym.schemas.audit import AuditManifest, EvidenceEntry
from verigym.schemas.provenance import BuildProvenance

AuditClassification = Literal["passed", "failed", "blocked", "skipped"]
_MAX_LOG_BYTES = 4 * 1024 * 1024
_REQUIRED_CHECKS = [
    "source.clean",
    "quality.format",
    "quality.lint",
    "quality.mypy",
    "quality.diff",
    "quality.docs",
    "schema.drift",
    "offline.core-no-tools",
    "local.icarus",
    "local.yosys",
    "docker.icarus",
    "docker.batch",
    "docker.yosys",
    "docker.yosys-batch",
    "profile.resolve-yosys",
    "verilog-eval.synthetic",
    "verilog-eval.external",
    "python.3.11",
    "python.3.12",
    "python.3.13",
    "package.build-frontend",
    "package.reproducible",
    "package.clean-provenance",
    "package.distribution-scan",
    "package.clean-dependency-install",
    "package.installed-wheel",
    "package.installed-sdist",
    "performance.plan-bound",
    "release.bundle-validation",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _safe_environment(updates: dict[str, str] | None = None) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(
            marker in key.upper()
            for marker in ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")
        )
    }
    environment.update(
        {
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": "",
        }
    )
    if updates:
        environment.update(updates)
    return environment


class AuditRunner:
    def __init__(
        self,
        root: Path,
        output: Path,
        *,
        docker_iverilog_image: str,
        docker_yosys_image: str,
        verilog_eval_root: Path | None,
        wheelhouse: Path | None,
        python_interpreters: dict[str, Path | None],
        source_date_epoch: int,
    ) -> None:
        self.root = root
        self.output = output
        self.commands = output / "commands"
        self.reports = output / "reports"
        self.packages = output / "packages"
        self.docker_iverilog_image = docker_iverilog_image
        self.docker_yosys_image = docker_yosys_image
        self.verilog_eval_root = verilog_eval_root
        self.wheelhouse = wheelhouse
        self.python_interpreters = python_interpreters
        self.source_date_epoch = source_date_epoch
        self.evidence: list[EvidenceEntry] = []
        self.created_at = _now()
        self.live_provenance = get_build_provenance()

    def _display_argument(self, argument: str) -> str:
        replacements = [
            (str(self.output.resolve()), "<audit-root>"),
            (str(self.root.resolve()), "<workspace>"),
            (str(Path.home().resolve()), "<home>"),
        ]
        if self.verilog_eval_root is not None:
            replacements.insert(
                0,
                (str(self.verilog_eval_root.resolve()), "<external-verilog-eval>"),
            )
        if self.wheelhouse is not None:
            replacements.insert(
                0,
                (str(self.wheelhouse.resolve()), "<dependency-wheelhouse>"),
            )
        for version, interpreter in self.python_interpreters.items():
            if interpreter is not None:
                replacements.insert(
                    0,
                    (str(interpreter.resolve()), f"<python-{version}>"),
                )
        result = argument
        for source, replacement in replacements:
            result = result.replace(source, replacement)
        return result

    def _sanitize(self, payload: bytes) -> str:
        text = payload.decode("utf-8", errors="replace")
        text = self._display_argument(text)
        text = re.sub(r"/tmp/[^\s'\"\\]]+", "<tmp>", text)
        text = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", text)
        text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "<redacted-api-key>", text)
        encoded = text.encode("utf-8")
        if len(encoded) <= _MAX_LOG_BYTES:
            return text
        half = _MAX_LOG_BYTES // 2
        return (
            encoded[:half].decode("utf-8", errors="replace")
            + "\n<output truncated by audit recorder>\n"
            + encoded[-half:].decode("utf-8", errors="replace")
        )

    def run(
        self,
        check_id: str,
        argv: list[str],
        *,
        environment: dict[str, str] | None = None,
        timeout: int = 900,
        identities: dict[str, Any] | None = None,
        output_paths: list[str] | None = None,
        required_files: list[Path] | None = None,
        failure_classification: AuditClassification = "failed",
        failure_reason: str | None = None,
    ) -> EvidenceEntry:
        started = _now()
        try:
            process = subprocess.run(
                argv,
                cwd=self.root,
                env=environment or _safe_environment(),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            exit_code: int | None = process.returncode
            output = self._sanitize(process.stdout)
            classification: AuditClassification = (
                "passed" if process.returncode == 0 else failure_classification
            )
            reason = (
                None
                if classification == "passed"
                else (failure_reason or f"command exited {process.returncode}")
            )
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            output = self._sanitize((exc.stdout or b"") + (exc.stderr or b""))
            classification = "failed"
            reason = f"command exceeded the {timeout}-second audit timeout"
        missing_outputs = [
            relative for relative in (output_paths or []) if not (self.output / relative).is_file()
        ]
        missing_required_files = [
            path.name for path in (required_files or []) if not path.is_file()
        ]
        missing_evidence = [*missing_outputs, *missing_required_files]
        if classification == "passed" and missing_evidence:
            classification = "failed"
            reason = "command did not produce required evidence: " + ", ".join(missing_evidence)
        ended = _now()
        relative_log = f"commands/{check_id}.log"
        log_path = self.output / relative_log
        log_path.parent.mkdir(parents=True, exist_ok=True)
        displayed = [self._display_argument(item) for item in argv]
        log_path.write_text(
            "\n".join(
                [
                    f"check_id: {check_id}",
                    f"command_argv: {json.dumps(displayed)}",
                    f"started_at: {started.isoformat()}",
                    f"ended_at: {ended.isoformat()}",
                    f"exit_code: {exit_code}",
                    f"classification: {classification}",
                    "",
                    output,
                ]
            ),
            encoding="utf-8",
        )
        paths = [relative_log, *(output_paths or [])]
        artifact_hashes = {
            relative: sha256_file(self.output / relative)
            for relative in paths
            if (self.output / relative).is_file()
        }
        recorded_identities = dict(identities or {})
        if required_files:
            recorded_identities["produced_files"] = {
                path.name: sha256_file(path) for path in required_files if path.is_file()
            }
        entry = EvidenceEntry(
            check_id=check_id,
            command_argv=displayed,
            started_at=started,
            ended_at=ended,
            exit_code=exit_code,
            package_provenance=self.live_provenance,
            identities=recorded_identities,
            classification=classification,
            output_paths=paths,
            artifact_hashes=artifact_hashes,
            reason=reason,
        )
        self.evidence.append(entry)
        print(f"{check_id}: {classification}")
        return entry

    def unavailable(
        self,
        check_id: str,
        argv: list[str],
        *,
        classification: Literal["blocked", "skipped"],
        reason: str,
        identities: dict[str, Any] | None = None,
    ) -> None:
        timestamp = _now()
        relative_log = f"commands/{check_id}.log"
        log_path = self.output / relative_log
        log_path.parent.mkdir(parents=True, exist_ok=True)
        displayed = [self._display_argument(item) for item in argv]
        log_path.write_text(
            "\n".join(
                [
                    f"check_id: {check_id}",
                    f"command_argv: {json.dumps(displayed)}",
                    f"started_at: {timestamp.isoformat()}",
                    f"ended_at: {timestamp.isoformat()}",
                    "exit_code: null",
                    f"classification: {classification}",
                    f"reason: {reason}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.evidence.append(
            EvidenceEntry(
                check_id=check_id,
                command_argv=displayed,
                started_at=timestamp,
                ended_at=timestamp,
                exit_code=None,
                package_provenance=self.live_provenance,
                identities=identities or {},
                classification=classification,
                output_paths=[relative_log],
                artifact_hashes={relative_log: sha256_file(log_path)},
                reason=reason,
            )
        )
        print(f"{check_id}: {classification}")

    def environment_inventory(self) -> dict[str, Any]:
        def capture(argv: list[str]) -> dict[str, Any]:
            if shutil.which(argv[0]) is None:
                return {"available": False}
            process = subprocess.run(
                argv,
                cwd=self.root,
                env=_safe_environment(),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=30,
            )
            return {
                "available": process.returncode == 0,
                "exit_code": process.returncode,
                "output": self._sanitize(process.stdout).strip()[:4096],
            }

        images = {}
        for name, reference in {
            "docker_iverilog": self.docker_iverilog_image,
            "docker_yosys": self.docker_yosys_image,
        }.items():
            images[name] = {
                "requested_reference": reference,
                "inspection": capture(
                    ["docker", "image", "inspect", "--format={{.Id}}", reference]
                ),
            }
        external_identity: dict[str, Any] | None = None
        if self.verilog_eval_root is not None:
            dataset = (
                self.verilog_eval_root
                if self.verilog_eval_root.name == "dataset_spec-to-rtl"
                else self.verilog_eval_root / "dataset_spec-to-rtl"
            )
            git_process = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD^{commit}"],
                cwd=self.verilog_eval_root,
                env=_safe_environment(),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            status_process = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.verilog_eval_root,
                env=_safe_environment(),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            external_identity = {
                "git_commit": (
                    git_process.stdout.decode("ascii").strip()
                    if git_process.returncode == 0
                    else None
                ),
                "dataset_content_hash": hash_directory(dataset),
                "checkout_clean_before": (
                    status_process.returncode == 0 and not status_process.stdout
                ),
                "path": "<external-verilog-eval>",
            }
        interpreter_inventory = {
            version: (
                capture([str(interpreter), "--version"])
                if interpreter is not None
                else {"available": False}
            )
            for version, interpreter in self.python_interpreters.items()
        }
        wheelhouse_inventory = {
            "provided": self.wheelhouse is not None,
            "file_count": (
                len([path for path in self.wheelhouse.iterdir() if path.is_file()])
                if self.wheelhouse is not None
                else 0
            ),
            "content_hash": (
                hash_directory(self.wheelhouse) if self.wheelhouse is not None else None
            ),
            "path": "<dependency-wheelhouse>" if self.wheelhouse is not None else None,
        }
        return {
            "schema_version": "1.0",
            "platform": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "system": platform.system(),
                "machine": platform.machine(),
            },
            "source": {
                "commit": capture(["git", "rev-parse", "--verify", "HEAD^{commit}"]),
                "tree": capture(["git", "rev-parse", "HEAD^{tree}"]),
                "branch": capture(["git", "branch", "--show-current"]),
                "provenance": self.live_provenance.model_dump(mode="json"),
            },
            "tools": {
                "docker": capture(["docker", "version"]),
                "iverilog": capture(["iverilog", "-V"]),
                "vvp": capture(["vvp", "-V"]),
                "yosys": capture(["yosys", "-V"]),
                "abc": capture(["yosys-abc", "-c", "version"]),
            },
            "images": images,
            "python_interpreters": interpreter_inventory,
            "dependency_wheelhouse": wheelhouse_inventory,
            "external_verilog_eval": {
                "provided": self.verilog_eval_root is not None,
                "identity": external_identity,
            },
        }

    def execute_checks(self) -> None:
        python = sys.executable
        self.run(
            "source.clean",
            [
                python,
                "scripts/verify_clean_source.py",
                "--output",
                str(self.reports / "source_identity.json"),
            ],
            output_paths=["reports/source_identity.json"],
        )
        self.run("quality.format", ["ruff", "format", "--check", "."])
        self.run("quality.lint", ["ruff", "check", "."])
        self.run("quality.mypy", ["mypy", "--strict", "src/verigym"])
        self.run("quality.diff", ["git", "diff", "--check"])
        self.run(
            "quality.docs",
            [
                python,
                "-m",
                "pytest",
                "-q",
                (
                    "tests/unit/test_audit_contracts.py::"
                    "test_required_documentation_and_adrs_exist_and_examples_compile"
                ),
            ],
        )
        self.run(
            "schema.drift",
            [python, "scripts/export_schemas.py", "--check"],
        )
        self.run(
            "offline.core-no-tools",
            [
                python,
                "-m",
                "pytest",
                "-m",
                "not docker and not yosys and not external_benchmark and not release_audit",
            ],
            environment=_safe_environment({"PATH": ""}),
            timeout=1200,
            identities={"network": "not configured", "optional_tool_path": "empty"},
        )
        self.run(
            "local.icarus",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "tests/integration/test_vertical_slice.py",
                "tests/integration/test_milestone5.py",
                "tests/integration/test_sampling_milestone6.py",
                "tests/integration/test_verilog_eval_milestone6.py",
                "tests/integration/test_experiments_milestone9.py",
            ],
            timeout=1200,
        )
        self.run(
            "local.yosys",
            [python, "-m", "pytest", "-m", "yosys"],
            environment=_safe_environment({"VERIGYM_RUN_YOSYS_TESTS": "1"}),
            timeout=600,
        )
        self.run(
            "docker.icarus",
            [python, "-m", "pytest", "-m", "docker"],
            environment=_safe_environment(
                {
                    "VERIGYM_RUN_DOCKER_TESTS": "1",
                    "VERIGYM_DOCKER_IMAGE": self.docker_iverilog_image,
                }
            ),
            timeout=1500,
            identities={"requested_image": self.docker_iverilog_image},
        )
        self.run(
            "docker.batch",
            [python, "-m", "pytest", "-m", "docker_batch"],
            environment=_safe_environment(
                {
                    "VERIGYM_RUN_DOCKER_BATCH_TESTS": "1",
                    "VERIGYM_DOCKER_IMAGE": self.docker_iverilog_image,
                }
            ),
            timeout=900,
            identities={"requested_image": self.docker_iverilog_image},
        )
        self.run(
            "docker.yosys",
            [python, "-m", "pytest", "-m", "docker_yosys"],
            environment=_safe_environment(
                {
                    "VERIGYM_RUN_DOCKER_YOSYS_TESTS": "1",
                    "VERIGYM_DOCKER_YOSYS_IMAGE": self.docker_yosys_image,
                }
            ),
            timeout=1500,
            identities={
                "requested_image": self.docker_yosys_image,
                "profile": "open-yosys-toy-area-v1",
            },
        )
        self.run(
            "docker.yosys-batch",
            [python, "-m", "pytest", "-m", "yosys_batch"],
            environment=_safe_environment(
                {
                    "VERIGYM_RUN_YOSYS_BATCH_TESTS": "1",
                    "VERIGYM_DOCKER_YOSYS_IMAGE": self.docker_yosys_image,
                }
            ),
            timeout=1200,
            identities={
                "requested_image": self.docker_yosys_image,
                "profile": "open-yosys-toy-area-v1",
            },
        )
        self.run(
            "profile.resolve-yosys",
            [
                python,
                "-m",
                "verigym",
                "profiles",
                "resolve",
                "open-yosys-toy-area-v1",
                "--runtime",
                "docker",
                "--docker-image",
                self.docker_yosys_image,
            ],
            timeout=300,
            identities={
                "requested_image": self.docker_yosys_image,
                "profile": "open-yosys-toy-area-v1",
            },
        )
        self.run(
            "verilog-eval.synthetic",
            [python, "-m", "pytest", "-m", "verilog_eval_batch"],
            environment=_safe_environment({"VERIGYM_RUN_VERILOG_EVAL_BATCH_TESTS": "1"}),
            timeout=600,
            identities={"source": "first-party synthetic fixture"},
        )
        if self.verilog_eval_root is None:
            self.unavailable(
                "verilog-eval.external",
                [python, "-m", "pytest", "-m", "external_benchmark"],
                classification="blocked",
                reason="no user-supplied real VerilogEval checkout was provided",
            )
        else:
            self.run(
                "verilog-eval.external",
                [python, "-m", "pytest", "-s", "-m", "external_benchmark"],
                environment=_safe_environment(
                    {
                        "VERIGYM_VERILOG_EVAL_ROOT": str(self.verilog_eval_root),
                        "VERIGYM_VERILOG_EVAL_DOCKER_IMAGE": self.docker_iverilog_image,
                        "VERIGYM_EXTERNAL_EVIDENCE_OUTPUT": str(
                            self.reports / "external_verilog_eval.json"
                        ),
                    }
                ),
                timeout=1200,
                identities={
                    "source_path": "<external-verilog-eval>",
                    "requested_image": self.docker_iverilog_image,
                },
                output_paths=["reports/external_verilog_eval.json"],
            )

        frontend_files = [
            self.root / "dist" / "verigym-0.1.0-py3-none-any.whl",
            self.root / "dist" / "verigym-0.1.0.tar.gz",
        ]
        for frontend_file in frontend_files:
            frontend_file.unlink(missing_ok=True)
        self.run(
            "package.build-frontend",
            [
                python,
                "-m",
                "build",
            ],
            environment=_safe_environment(
                {
                    "PIP_INDEX_URL": "https://pypi.org/simple",
                    "SOURCE_DATE_EPOCH": str(self.source_date_epoch),
                }
            ),
            timeout=600,
            required_files=frontend_files,
        )
        self.run(
            "package.reproducible",
            [
                python,
                "scripts/reproducible_build.py",
                "--package-output",
                str(self.packages),
                "--report",
                str(self.output / "reproducible_build.json"),
                "--source-date-epoch",
                str(self.source_date_epoch),
            ],
            environment=_safe_environment({"SOURCE_DATE_EPOCH": str(self.source_date_epoch)}),
            timeout=900,
            output_paths=[
                "reproducible_build.json",
                "packages/verigym-0.1.0-py3-none-any.whl",
                "packages/verigym-0.1.0.tar.gz",
            ],
        )
        self.run(
            "package.clean-provenance",
            [
                python,
                "scripts/verify_build_provenance.py",
                "--report",
                str(self.output / "reproducible_build.json"),
                "--source-date-epoch",
                str(self.source_date_epoch),
            ],
        )
        wheel = self.packages / "verigym-0.1.0-py3-none-any.whl"
        sdist = self.packages / "verigym-0.1.0.tar.gz"
        if wheel.is_file() and sdist.is_file():
            self.run(
                "package.distribution-scan",
                [
                    python,
                    "scripts/audit_distribution.py",
                    "--wheel",
                    str(wheel),
                    "--sdist",
                    str(sdist),
                    "--output",
                    str(self.output / "distribution_inventory.json"),
                ],
                output_paths=["distribution_inventory.json"],
            )
            python_311 = self.python_interpreters.get("3.11")
            if self.wheelhouse is None or python_311 is None:
                self.unavailable(
                    "package.clean-dependency-install",
                    [python, "scripts/clean_install_smoke.py", "--wheel", str(wheel)],
                    classification="blocked",
                    reason=(
                        "a dependency wheelhouse and Python 3.11 interpreter are required "
                        "for clean offline resolution"
                    ),
                )
            else:
                self.run(
                    "package.clean-dependency-install",
                    [
                        python,
                        "scripts/clean_install_smoke.py",
                        "--wheel",
                        str(wheel),
                        "--wheelhouse",
                        str(self.wheelhouse),
                        "--python",
                        str(python_311),
                        "--expected-python",
                        "3.11",
                        "--source-root",
                        str(self.root),
                        "--output",
                        str(self.reports / "clean_dependency_install.json"),
                    ],
                    timeout=600,
                    identities={"dependency_resolution": "offline_hashed_wheelhouse"},
                    output_paths=["reports/clean_dependency_install.json"],
                )
            for version in ("3.11", "3.12", "3.13"):
                interpreter = self.python_interpreters.get(version)
                check_id = f"python.{version}"
                if interpreter is None:
                    self.unavailable(
                        check_id,
                        [f"python{version}", "<installed-package-check>"],
                        classification="skipped",
                        reason=f"Python {version} interpreter was not supplied to the audit",
                    )
                elif self.wheelhouse is None:
                    self.unavailable(
                        check_id,
                        [str(interpreter), "<installed-package-check>"],
                        classification="blocked",
                        reason="installed-package Python checks require a dependency wheelhouse",
                    )
                else:
                    report_name = f"python_{version.replace('.', '_')}_installed.json"
                    self.run(
                        check_id,
                        [
                            python,
                            "scripts/clean_install_smoke.py",
                            "--wheel",
                            str(wheel),
                            "--wheelhouse",
                            str(self.wheelhouse),
                            "--python",
                            str(interpreter),
                            "--expected-python",
                            version,
                            "--source-root",
                            str(self.root),
                            "--output",
                            str(self.reports / report_name),
                        ],
                        timeout=600,
                        identities={
                            "declared_python": version,
                            "dependency_resolution": "offline_hashed_wheelhouse",
                        },
                        output_paths=[f"reports/{report_name}"],
                    )
            self.run(
                "package.installed-wheel",
                [
                    python,
                    "scripts/installed_conformance.py",
                    "--wheel",
                    str(wheel),
                    "--output",
                    str(self.reports / "installed_conformance.json"),
                ],
                timeout=600,
                output_paths=["reports/installed_conformance.json"],
            )
            self.run(
                "package.installed-sdist",
                [
                    python,
                    "scripts/sdist_conformance.py",
                    "--sdist",
                    str(sdist),
                    "--output",
                    str(self.reports / "sdist_conformance.json"),
                ],
                timeout=600,
                output_paths=["reports/sdist_conformance.json"],
            )
        else:
            for check_id in (
                "package.distribution-scan",
                "package.clean-dependency-install",
                "package.installed-wheel",
                "package.installed-sdist",
                "python.3.11",
                "python.3.12",
                "python.3.13",
            ):
                self.unavailable(
                    check_id,
                    [python, "<package-check>"],
                    classification="blocked",
                    reason="reproducible build did not produce the required archive",
                )
        self.run(
            "performance.plan-bound",
            [
                python,
                "scripts/performance_smoke.py",
                "--output",
                str(self.reports / "performance_smoke.json"),
            ],
            timeout=600,
            output_paths=["reports/performance_smoke.json"],
        )

    def _package_provenance(self) -> BuildProvenance:
        report = self.output / "reproducible_build.json"
        if report.is_file():
            raw = json.loads(report.read_text(encoding="utf-8"))
            try:
                return BuildProvenance.model_validate(raw["embedded_provenance"])
            except (KeyError, ValueError, TypeError):
                pass
        return self.live_provenance

    def _schema_inventory(self) -> dict[str, Any]:
        schemas = sorted((self.root / "docs/schemas").glob("*.schema.json"))
        goldens = sorted((self.root / "tests/fixtures/golden/v1").rglob("*"))
        return {
            "schema_version": "1.0",
            "current_schema_version": "1.0",
            "compatibility_policy": "explicit major/minor dispatch; unknown major rejected",
            "schema_count": len(schemas),
            "schemas": [
                {
                    "path": path.relative_to(self.root).as_posix(),
                    "sha256": sha256_file(path),
                }
                for path in schemas
            ],
            "golden_file_count": sum(path.is_file() for path in goldens),
            "golden_files": [
                {
                    "path": path.relative_to(self.root).as_posix(),
                    "sha256": sha256_file(path),
                }
                for path in goldens
                if path.is_file()
            ],
            "drift_check": "schema.drift",
            "compatibility_tests": "offline.core-no-tools",
        }

    def _artifact_inventory(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "integrity_contract": {
                "new_runs": "artifact_manifest.json required",
                "new_experiments": "artifact_manifest.json binds parent and child identities",
                "legacy": "readable as legacy_unverified",
                "tamper": "distinct artifact_integrity error",
            },
            "persistent_groups": [
                "task and suite source snapshots",
                "run config, manifest, trace, candidate metadata, scorecard, replay evidence",
                "model request/response/observed identity and plugin descriptors",
                "tool/verifier results and declared/resolved profiles",
                "sample-set manifest and pass-at-k report",
                "experiment config, plan, events, state, index, manifest, and reports",
                "build provenance and artifact manifests",
            ],
            "schema_inventory": "schema_inventory.json",
            "golden_root": "tests/fixtures/golden/v1 (hashes only; files are not copied)",
        }

    def _status(self, check_ids: list[str]) -> str:
        statuses = {entry.classification for entry in self.evidence if entry.check_id in check_ids}
        if not statuses or "failed" in statuses:
            return "fail"
        if "blocked" in statuses or "skipped" in statuses:
            return "blocked"
        return "pass"

    def _compliance(self) -> dict[str, Any]:
        mapping = [
            ("clean_python_311_install", ["python.3.11", "package.clean-dependency-install"]),
            ("doctor_without_commercial_tools", ["package.installed-wheel"]),
            ("toy_chat_and_agent_eval", ["local.icarus"]),
            ("hidden_verifier_isolation", ["offline.core-no-tools", "docker.icarus"]),
            ("run_artifact_layout_and_integrity", ["offline.core-no-tools"]),
            ("good_bad_and_error_distinctions", ["local.icarus", "docker.icarus"]),
            ("budgets_and_termination", ["offline.core-no-tools"]),
            ("model_free_replay", ["local.icarus", "docker.icarus", "docker.yosys"]),
            ("external_verilog_eval", ["verilog-eval.external"]),
            ("sampling_and_canonical_pass_at_k", ["local.icarus", "verilog-eval.synthetic"]),
            ("yosys_area_and_comparison_safeguards", ["local.yosys", "docker.yosys"]),
            ("batch_resume_and_reporting", ["offline.core-no-tools", "docker.batch"]),
            ("schemas_and_golden_compatibility", ["schema.drift", "offline.core-no-tools"]),
            ("installed_plugin_and_python_api", ["package.installed-wheel"]),
            ("documentation_and_extension_guides", ["quality.docs"]),
        ]
        return {
            "schema_version": "1.0",
            "requirements": [
                {
                    "id": requirement,
                    "status": self._status(checks),
                    "evidence_ids": checks,
                }
                for requirement, checks in mapping
            ],
            "authoritative_human_matrix": "reports/MVP_COMPLIANCE.md",
        }

    def _test_summary(self) -> dict[str, Any]:
        test_entries = [
            entry
            for entry in self.evidence
            if entry.check_id.startswith(
                ("offline.", "local.", "docker.", "verilog-eval.", "quality.docs")
            )
        ]
        summaries = []
        for entry in test_entries:
            log = (self.output / entry.output_paths[0]).read_text(encoding="utf-8")
            matches = re.findall(r"(\d+) passed", log)
            skips = re.findall(r"(\d+) skipped", log)
            summaries.append(
                {
                    "check_id": entry.check_id,
                    "classification": entry.classification,
                    "exit_code": entry.exit_code,
                    "reported_passed": int(matches[-1]) if matches else None,
                    "reported_skipped": int(skips[-1]) if skips else None,
                    "log": entry.output_paths[0],
                }
            )
        return {"schema_version": "1.0", "checks": summaries}

    def _security_summary(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": self._status(["offline.core-no-tools", "docker.icarus", "docker.yosys"]),
            "verified_evidence": [
                "offline.core-no-tools",
                "local.icarus",
                "docker.icarus",
                "docker.yosys",
                "package.distribution-scan",
            ],
            "docker_host_dependent": True,
            "local_runtime": "local_trusted",
            "plugin_execution": (
                "trusted installed host code; supported interfaces remain policy-bound"
            ),
            "residual_risks": [
                "Docker shares the audited host kernel and daemon",
                "remote model services remain mutable",
                "legacy artifacts without manifests are legacy_unverified",
            ],
            "human_report": "docs/audits/mvp_security_audit.md",
        }

    def _write_evidence(self) -> None:
        _write_json(
            self.output / "evidence.json",
            {
                "schema_version": "1.0",
                "entries": [entry.model_dump(mode="json") for entry in self.evidence],
            },
        )

    def assemble(self) -> None:
        _write_json(self.output / "schema_inventory.json", self._schema_inventory())
        _write_json(self.output / "artifact_inventory.json", self._artifact_inventory())
        _write_json(self.output / "compliance.json", self._compliance())
        _write_json(self.output / "test_summary.json", self._test_summary())
        _write_json(self.output / "security_summary.json", self._security_summary())
        if not (self.output / "distribution_inventory.json").is_file():
            _write_json(
                self.output / "distribution_inventory.json",
                {
                    "schema_version": "1.0",
                    "status": "failed",
                    "issues": ["package distribution scan did not produce evidence"],
                },
            )
        if not (self.output / "reproducible_build.json").is_file():
            _write_json(
                self.output / "reproducible_build.json",
                {
                    "schema_version": "1.0",
                    "status": "failed",
                    "issues": ["reproducible build did not produce evidence"],
                },
            )
        self._write_evidence()
        provenance = self._package_provenance()
        gate, reasons = evaluate_gate(self.evidence, provenance, _REQUIRED_CHECKS)
        manifest = AuditManifest(
            audit_id="verigym-0.1.0-mvp-rc-audit",
            created_at=self.created_at,
            package_version="0.1.0",
            package_provenance=provenance,
            required_check_ids=_REQUIRED_CHECKS,
            gate_result=gate,
            gate_reasons=reasons,
            evidence_sha256=sha256_file(self.output / "evidence.json"),
        )
        _write_json(
            self.output / "audit_manifest.json",
            manifest.model_dump(mode="json"),
        )
        self.reports.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            self.root / "docs/MVP_COMPLIANCE.md",
            self.reports / "MVP_COMPLIANCE.md",
        )
        evidence_rows = "\n".join(
            f"| `{entry.check_id}` | {entry.classification} | "
            f"{entry.exit_code if entry.exit_code is not None else 'not run'} | "
            f"`{entry.output_paths[0]}` |"
            for entry in self.evidence
        )
        reason_lines = "\n".join(f"- {reason}" for reason in reasons) or "- None."
        (self.reports / "MVP_AUDIT_REPORT.md").write_text(
            "\n".join(
                [
                    "# VeriGym MVP release-candidate audit",
                    "",
                    f"MVP RELEASE-CANDIDATE GATE: {gate}",
                    "",
                    "Package: `verigym 0.1.0`",
                    f"Source commit: `{provenance.source_commit or 'unknown'}`",
                    f"Source-tree SHA-256: `{provenance.source_tree_hash or 'unknown'}`",
                    f"Dirty build: `{provenance.dirty}`",
                    "",
                    "## Gate reasons",
                    "",
                    reason_lines,
                    "",
                    "## Executed evidence",
                    "",
                    "| Check | Classification | Exit | Log |",
                    "|---|---:|---:|---|",
                    evidence_rows,
                    "",
                    "No formal/OpenROAD/full-PPA, commercial execution, repository adapter, "
                    "external agent framework, trajectory/RL, distributed, or evolving-release "
                    "scope was started.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        checklist = [
            "# Release checklist",
            "",
            f"Overall gate: **{gate}**",
            "",
        ]
        by_id = {entry.check_id: entry for entry in self.evidence}
        for check_id in _REQUIRED_CHECKS:
            entry = by_id.get(check_id)
            if entry is None:
                checklist.append(f"- [ ] `{check_id}` — not run")
            else:
                checklist.append(
                    f"- [{'x' if entry.classification == 'passed' else ' '}] "
                    f"`{check_id}` — {entry.classification}"
                    + (f": {entry.reason}" if entry.reason else "")
                )
        checklist.append("")
        (self.reports / "RELEASE_CHECKLIST.md").write_text(
            "\n".join(checklist),
            encoding="utf-8",
        )
        write_hash_manifest(self.output)

    def validate_and_record(self) -> None:
        self.assemble()
        self.run(
            "release.bundle-validation",
            [sys.executable, "-m", "pytest", "-m", "release_audit"],
            environment=_safe_environment(
                {"VERIGYM_RELEASE_AUDIT_ROOT": str(self.output.resolve())}
            ),
            timeout=300,
        )
        self.assemble()
        _manifest, bundle_hash = validate_bundle(self.output)
        print(f"audit_bundle={self.output}")
        print(f"audit_bundle_hash={bundle_hash}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("release_audit"))
    parser.add_argument(
        "--docker-iverilog-image",
        default="verigym/rtl-iverilog:12.0",
    )
    parser.add_argument(
        "--docker-yosys-image",
        default="verigym/open-rtl-tools:iverilog12-yosys067",
    )
    parser.add_argument("--verilog-eval-root", type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--python-311", type=Path, default=Path(sys.executable))
    parser.add_argument("--python-312", type=Path)
    parser.add_argument("--python-313", type=Path)
    parser.add_argument("--source-date-epoch", type=int, default=1_784_712_454)
    arguments = parser.parse_args()
    root = Path.cwd().resolve()
    output = arguments.output.resolve()
    if output.exists():
        parser.error("audit output already exists; choose a new path to preserve evidence")
    if arguments.verilog_eval_root is not None and not arguments.verilog_eval_root.is_dir():
        parser.error("the supplied VerilogEval root is not a directory")
    if arguments.wheelhouse is not None and not arguments.wheelhouse.is_dir():
        parser.error("the supplied dependency wheelhouse is not a directory")
    python_interpreters = {
        "3.11": arguments.python_311,
        "3.12": arguments.python_312,
        "3.13": arguments.python_313,
    }
    for version, interpreter in python_interpreters.items():
        if interpreter is not None and (
            not interpreter.is_file() or not os.access(interpreter, os.X_OK)
        ):
            parser.error(f"the supplied Python {version} interpreter is not executable")
    source_status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    if source_status:
        parser.error("release audit requires a clean committed Git worktree")
    output.mkdir(parents=True)
    runner = AuditRunner(
        root,
        output,
        docker_iverilog_image=arguments.docker_iverilog_image,
        docker_yosys_image=arguments.docker_yosys_image,
        verilog_eval_root=arguments.verilog_eval_root,
        wheelhouse=(arguments.wheelhouse.resolve() if arguments.wheelhouse is not None else None),
        python_interpreters={
            version: interpreter.resolve() if interpreter is not None else None
            for version, interpreter in python_interpreters.items()
        },
        source_date_epoch=arguments.source_date_epoch,
    )
    _write_json(output / "environment.json", runner.environment_inventory())
    runner.execute_checks()
    runner.validate_and_record()
    manifest, _bundle_hash = validate_bundle(output)
    return 0 if manifest.gate_result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
