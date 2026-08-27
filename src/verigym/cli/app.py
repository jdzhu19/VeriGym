"""VeriGym command-line interface for toy RTL and external VerilogEval V2."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.table import Table

from verigym.campaign.service import CampaignService
from verigym.core.errors import VeriGymError
from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.evolution.comparison import build_evolving_evaluation
from verigym.evolution.exporter import (
    TrajectoryExporter,
    inspect_trajectory_source,
    replay_trajectory_dataset,
    validate_trajectory_dataset,
)
from verigym.evolution.memory import (
    prepare_training_summary,
    validate_agent_version,
    validate_memory_pack,
)
from verigym.evolution.splits import (
    scan_contamination,
    validate_contamination_scan,
    validate_task_split,
)
from verigym.evolution.versions import (
    freeze_context_update,
    replay_context_update,
    validate_run_version_assignments,
)
from verigym.experiments.config import load_experiment_config
from verigym.experiments.planner import ExperimentPlanner
from verigym.experiments.runner import BatchRunner
from verigym.experiments.schemas import ExperimentConfig
from verigym.experiments.state import (
    atomic_dump_json,
    load_json_model,
    load_jsonl_models,
)
from verigym.profiles.comparison import compare_area, compare_power, compare_timing
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.profiles.validation import validate_profile
from verigym.provenance import get_build_provenance
from verigym.registry.collections import Registries, build_registries
from verigym.reporting.service import ReportService
from verigym.runtimes.docker.diagnostics import diagnose_docker
from verigym.schemas.common import InteractionMode, ToolchainProfile
from verigym.schemas.evolution import (
    AgentUpdateManifest,
    AgentVersionManifest,
    AgentVersionSetManifest,
    EpisodeTrajectory,
    MemoryPack,
    RunAgentVersionAssignments,
    SanitizedTrainingSummary,
    TaskSplitManifest,
)
from verigym.schemas.model import ModelRunConfig
from verigym.schemas.options import JsonValue, validate_plugin_options
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.sampling import SampleSetResult
from verigym.schemas.suite import SuiteSourceConfig
from verigym.tools.base import SynthesisBackendPlugin
from verigym.tools.yosys.identity import local_abc_health
from verigym.version import __version__

app = typer.Typer(
    name="verigym",
    help="Execute reproducible RTL agent tasks and emit replayable scorecards.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
suites_app = typer.Typer(help="List and inspect benchmark suite adapters.")
tasks_app = typer.Typer(help="List and inspect normalized tasks.")
tools_app = typer.Typer(help="List and health-check structured tool plugins.")
agents_app = typer.Typer(help="List and inspect agent-harness plugins.")
models_app = typer.Typer(help="List and inspect model-client plugins.")
profiles_app = typer.Typer(help="List, validate, and resolve immutable toolchain profiles.")
report_app = typer.Typer(help="Offline reports and strict compatible-metric comparisons.")
campaign_app = typer.Typer(help="Combine frozen chat, agent, and evolving evaluations offline.")
trajectories_app = typer.Typer(help="Export and validate bounded observable trajectories.")
evolve_app = typer.Typer(help="Prepare and compare immutable context-memory agent versions.")
app.add_typer(suites_app, name="suites")
app.add_typer(tasks_app, name="tasks")
app.add_typer(tools_app, name="tools")
app.add_typer(agents_app, name="agents")
app.add_typer(models_app, name="models")
app.add_typer(profiles_app, name="profiles")
app.add_typer(report_app, name="report")
app.add_typer(campaign_app, name="campaign")
app.add_typer(trajectories_app, name="trajectories")
app.add_typer(evolve_app, name="evolve")
console = Console()


def _fail(exc: Exception) -> None:
    if isinstance(exc, VeriGymError):
        code = exc.exit_code
    elif isinstance(exc, (ValueError, FileNotFoundError)):
        code = 2
    else:
        code = 5
    console.print(f"[red]error:[/red] {exc}")
    raise typer.Exit(code=code) from exc


def _load_profile_file(
    registries: Registries,
    path: Path | None,
    *,
    expected_id: str | None = None,
) -> ToolchainProfile | None:
    if path is None:
        return None
    profile = registries.profiles.load_file(path)
    if expected_id is not None and profile.id != expected_id:
        raise ValueError(f"profile file declares {profile.id!r}, expected {expected_id!r}")
    return profile


def _synthesis_backend(registries: Registries, profile: ToolchainProfile) -> SynthesisBackendPlugin:
    if profile.flow is None:
        raise ValueError(f"profile {profile.id!r} has no synthesis flow")
    candidate = registries.tools.get(profile.flow.backend_plugin)
    if not isinstance(candidate, SynthesisBackendPlugin):
        raise ValueError(f"tool {profile.flow.backend_plugin!r} is not a synthesis backend")
    return candidate


def _source_config(
    source: Path | None,
    variant: str | None,
    *,
    strict_compatibility: bool,
) -> SuiteSourceConfig | None:
    if source is None:
        if variant is not None:
            raise ValueError("a suite variant requires an external source path")
        return None
    return SuiteSourceConfig(
        source_root=source,
        variant=variant,
        strict_compatibility=strict_compatibility,
    )


def _plugin_options(values: list[str] | None, *, flag: str) -> dict[str, JsonValue]:
    parsed: dict[str, object] = {}
    for assignment in values or []:
        if "=" not in assignment:
            raise ValueError(f"{flag} values must use KEY=JSON")
        key, encoded = assignment.split("=", 1)
        if key in parsed:
            raise ValueError(f"{flag} key {key!r} was repeated")
        try:
            parsed[key] = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{flag} value for {key!r} is not valid JSON") from exc
    return validate_plugin_options(parsed)


def _named_paths(values: list[str], *, flag: str) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for assignment in values:
        if "=" not in assignment:
            raise ValueError(f"{flag} values must use NAME=PATH")
        name, raw_path = assignment.split("=", 1)
        if not name or name in parsed:
            raise ValueError(f"{flag} contains an empty or repeated name")
        parsed[name] = Path(raw_path)
    return parsed


def _named_hashes(values: list[str], *, flag: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for assignment in values:
        if "=" not in assignment:
            raise ValueError(f"{flag} values must use NAME=SHA256")
        name, digest = assignment.split("=", 1)
        if not name or name in parsed:
            raise ValueError(f"{flag} contains an empty or repeated name")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"{flag} identities must be lowercase SHA-256 values")
        parsed[name] = digest
    return parsed


def _load_version_set(path: Path) -> dict[str, AgentVersionManifest]:
    version_set = load_json_model(path, AgentVersionSetManifest)
    versions: dict[str, AgentVersionManifest] = {}
    for version in version_set.versions:
        validate_agent_version(version)
        if version.agent_version_id in versions:
            raise ValueError("agent version set repeats an identity")
        versions[version.agent_version_id] = version
    if (
        content_hash([versions[key].model_dump(mode="json") for key in sorted(versions)])
        != version_set.version_set_hash
    ):
        raise ValueError("agent version-set identity changed")
    return versions


def _print_sample_result(result: SampleSetResult) -> None:
    report = result.report
    status = "VALID" if report.canonical_valid else "INVALID"
    style = "green" if report.canonical_valid else "red"
    console.print(
        f"[{style}]{status}[/{style}] pass@k for {report.task_id}: "
        f"n={report.requested_sample_count}, c={report.resolved_count}"
    )
    for entry in report.entries:
        value = f"{entry.value:.12g}" if entry.valid and entry.value is not None else "unavailable"
        suffix = f" ({entry.invalid_reason})" if entry.invalid_reason else ""
        console.print(f"pass@{entry.k}={value}{suffix}")
    for child in report.child_runs:
        console.print(
            f"sample[{child.sample_index:04d}] {child.outcome.value}: "
            f"{result.group_dir / child.relative_path}"
        )
    console.print(f"Sample group: {result.group_dir}")
    console.print(f"Aggregate report: {result.group_dir / 'pass_at_k.json'}")


@app.callback()
def callback(
    version: bool = typer.Option(False, "--version", help="Show the installed version."),
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()


@app.command("init")
def init_project(path: Path = typer.Argument(Path("."), help="Project directory.")) -> None:
    """Create a minimal local project configuration without overwriting files."""

    root = path.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    config = root / "verigym.yaml"
    if config.exists():
        _fail(ValueError(f"configuration already exists: {config}"))
    (root / ".verigym").mkdir(exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)
    config.write_text(
        'schema_version: "1.0"\npaths:\n  runs: "runs"\nruntime:\n  default: "local"\n',
        encoding="utf-8",
    )
    console.print(f"Initialized VeriGym project at [bold]{root}[/bold]")


@app.command("doctor")
def doctor(
    docker_image: str | None = typer.Option(
        None,
        "--docker-image",
        help="Inspect this local image without pulling or building it.",
    ),
    toolchain_profile: str | None = typer.Option(
        None,
        "--toolchain-profile",
        help="Validate and, with --docker-image, resolve this profile without a model call.",
    ),
    toolchain_profile_file: Path | None = typer.Option(
        None,
        "--toolchain-profile-file",
        exists=True,
        dir_okay=False,
        help="Load one site-specific profile before validation.",
    ),
) -> None:
    """Report package, runtime, and tool health without printing secrets."""

    try:
        registries = build_registries()
        _load_profile_file(
            registries,
            toolchain_profile_file,
            expected_id=toolchain_profile,
        )
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)
        return
    table = Table(title="VeriGym doctor")
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Details")
    table.add_row("Python", "ok", sys.version.split()[0])
    table.add_row("VeriGym", "ok", __version__)
    provenance = get_build_provenance()
    provenance_identity = provenance.source_tree_hash or "unknown"
    table.add_row(
        "Build provenance",
        "ok" if provenance.source_tree_hash and provenance.source_commit else "unknown",
        (
            f"{provenance.provenance_method}; commit="
            f"{provenance.source_commit or 'unknown'}; tree={provenance_identity}; "
            f"dirty={provenance.dirty}"
        ),
    )
    for diagnostic in diagnose_docker(docker_image):
        table.add_row(
            diagnostic.component,
            "ok" if diagnostic.healthy else "unavailable",
            diagnostic.message,
        )
    for name, runtime in registries.runtimes.items():
        health = runtime.health_check()
        table.add_row(f"runtime:{name}", "ok" if health.healthy else "missing", health.message)
    for name, suite in registries.suites.items():
        table.add_row(
            f"suite:{name}",
            "ok",
            f"{suite.descriptor.suite_version} ({suite.descriptor.provider})",
        )
    for name, agent_plugin in registries.agents.items():
        table.add_row(
            f"agent:{name}",
            "ok",
            f"{agent_plugin.descriptor.version} ({agent_plugin.descriptor.provider})",
        )
    for name, model_plugin in registries.models.items():
        table.add_row(
            f"model:{name}",
            "ok",
            f"{model_plugin.descriptor.model_id} ({model_plugin.descriptor.provider})",
        )
    for name, tool in registries.tools.items():
        health = tool.health_check()
        table.add_row(f"tool:{name}", "ok" if health.healthy else "missing", health.message)
    for plugin_diagnostic in registries.diagnostics():
        origin = plugin_diagnostic.origin
        table.add_row(
            f"plugin:{plugin_diagnostic.group}:{plugin_diagnostic.entry_point}",
            "ok" if plugin_diagnostic.status == "loaded" else "rejected",
            (
                f"{origin.package or 'unknown'} {origin.version or 'unknown'}; "
                f"{plugin_diagnostic.message}"
            ),
        )
    abc = local_abc_health()
    table.add_row("tool:yosys-abc", "ok" if abc.healthy else "missing", abc.message)
    for profile_id, profile in registries.profiles.items():
        validation = validate_profile(profile, _synthesis_backend(registries, profile))
        table.add_row(
            f"profile:{profile_id}",
            "ok" if validation.valid else "invalid",
            "statically valid" if validation.valid else "; ".join(validation.errors),
        )
    if toolchain_profile is not None:
        try:
            profile = registries.profiles.get(toolchain_profile)
            if docker_image is None:
                table.add_row(
                    f"profile-resolution:{toolchain_profile}",
                    "not-run",
                    "pass --docker-image to resolve this Docker profile",
                )
            else:
                service = VeriGym(registries)
                task_id = str(profile.metadata.get("acceptance_task", ""))
                suite, task, _assets = service.load_task(task_id)
                runtime = registries.runtimes.get("docker").configure(
                    DockerRuntimeConfig(image=docker_image, pull_policy="never")
                )
                try:
                    runtime.prepare(f"doctor-profile-{uuid.uuid4().hex[:12]}")
                    reference = suite.reference_solution(task)
                    resolved = resolve_toolchain_profile(
                        profile,
                        runtime,
                        source_paths=list(task.workspace.entrypoints),
                        top_module=profile.flow.top_module if profile.flow is not None else "",
                        reference_candidate_hash=(
                            content_hash(reference) if reference is not None else None
                        ),
                        backend=_synthesis_backend(registries, profile),
                    )
                    table.add_row(
                        f"profile-resolution:{toolchain_profile}",
                        "ok",
                        resolved.resolved_profile_hash,
                    )
                finally:
                    runtime.close()
        except Exception as exc:
            table.add_row(
                f"profile-resolution:{toolchain_profile}",
                "invalid",
                str(exc),
            )
    console.print(table)


@app.command("run")
def run_task(
    suite: str = typer.Option(..., "--suite", help="Suite plugin slug."),
    task: str = typer.Option(..., "--task", help="Native task ID or full task ID."),
    mode: InteractionMode = typer.Option(InteractionMode.AGENT, "--mode"),
    agent: str = typer.Option("scripted", "--agent"),
    model: str | None = typer.Option(None, "--model", help="Model-client plugin slug."),
    model_base_url: str | None = typer.Option(
        None,
        "--model-base-url",
        help="OpenAI-compatible base URL without embedded credentials.",
    ),
    model_base_url_env: str | None = typer.Option(
        None,
        "--model-base-url-env",
        help="Name of the environment variable containing an OpenAI-compatible base URL.",
    ),
    model_provider_id: str | None = typer.Option(
        None,
        "--model-provider-id",
        help="Provider identity label for a generic configurable model client.",
    ),
    model_id: str | None = typer.Option(
        None,
        "--model-id",
        help="Provider model identifier for a configurable model client.",
    ),
    model_api_key_env: str | None = typer.Option(
        None,
        "--model-api-key-env",
        help="Name of the environment variable containing the model credential.",
    ),
    model_connect_timeout_s: float = typer.Option(10.0, "--model-connect-timeout-s"),
    model_read_timeout_s: float = typer.Option(60.0, "--model-read-timeout-s"),
    model_request_timeout_s: float = typer.Option(90.0, "--model-request-timeout-s"),
    model_max_response_bytes: int = typer.Option(
        4 * 1024 * 1024,
        "--model-max-response-bytes",
        min=1024,
    ),
    model_require_exact_model_id: bool = typer.Option(
        False,
        "--model-require-exact-id/--model-allow-observed-id",
    ),
    model_option: list[str] | None = typer.Option(
        None,
        "--model-option",
        help="Repeat secret-free model plugin options as KEY=JSON.",
    ),
    temperature: float = typer.Option(0.0, "--temperature", min=0.0),
    top_p: float | None = typer.Option(None, "--top-p", min=0.000000001, max=1.0),
    max_invalid_actions: int = typer.Option(3, "--max-invalid-actions", min=1),
    agent_option: list[str] | None = typer.Option(
        None,
        "--agent-option",
        help="Repeat secret-free agent plugin options as KEY=JSON.",
    ),
    suite_source: Path | None = typer.Option(
        None,
        "--suite-source",
        help="External benchmark repository/dataset path; VeriGym never auto-downloads it.",
    ),
    suite_variant: str | None = typer.Option(None, "--suite-variant"),
    strict_compatibility: bool = typer.Option(
        True,
        "--strict-compatibility/--no-strict-compatibility",
    ),
    samples: int = typer.Option(1, "--samples", min=1),
    pass_k: list[int] | None = typer.Option(None, "--pass-k", min=1),
    runtime: str = typer.Option("local", "--runtime"),
    docker_image: str | None = typer.Option(
        None,
        "--docker-image",
        help=(
            "Prebuilt local image reference; DockerRuntime never builds and does not pull "
            "by default."
        ),
    ),
    docker_pull_policy: Literal["never", "if_missing"] = typer.Option(
        "never",
        "--docker-pull-policy",
        help="Image policy: never (default) or explicit if_missing.",
    ),
    docker_user: str | None = typer.Option(None, "--docker-user"),
    docker_memory_bytes: int = typer.Option(
        512 * 1024 * 1024,
        "--docker-memory-bytes",
        min=64 * 1024 * 1024,
    ),
    docker_cpus: float = typer.Option(1.0, "--docker-cpus", min=0.1),
    docker_pids_limit: int = typer.Option(128, "--docker-pids-limit", min=16),
    docker_tmpfs_bytes: int = typer.Option(
        64 * 1024 * 1024,
        "--docker-tmpfs-bytes",
        min=1024 * 1024,
    ),
    docker_stop_timeout_s: int = typer.Option(3, "--docker-stop-timeout-s", min=1),
    docker_max_command_time_s: int = typer.Option(
        60,
        "--docker-max-command-time-s",
        min=1,
    ),
    docker_environment_allowlist: list[str] | None = typer.Option(
        None,
        "--docker-environment-allow",
        help="Repeat for non-secret environment names explicitly allowed into containers.",
    ),
    toolchain_profile: str | None = typer.Option(
        None,
        "--toolchain-profile",
        help="Opt in to an immutable synthesis-quality profile.",
    ),
    toolchain_profile_file: Path | None = typer.Option(
        None,
        "--toolchain-profile-file",
        exists=True,
        dir_okay=False,
        help="Load a site-specific synthesis profile from YAML or JSON.",
    ),
    agent_ppa_feedback: bool = typer.Option(
        False,
        "--agent-ppa-feedback",
        help="Enable revision-bound candidate-only PPA feedback for an RTLLM AgentEval task.",
    ),
    agent_ppa_max_calls: int = typer.Option(
        3,
        "--agent-ppa-max-calls",
        min=1,
        max=8,
        help="Maximum real agent-visible synthesis executions (cached calls remain tool calls).",
    ),
    seed: int = typer.Option(0, "--seed"),
    output: Path = typer.Option(Path("runs"), "--output"),
) -> None:
    """Run one normalized task end to end.

    Docker example: verigym run --suite toy-rtl --task counter-basic --mode agent
    --agent scripted --runtime docker --docker-image verigym/rtl-iverilog:12.0
    --output runs/
    """

    task_id = task if "/" in task else f"{suite}/{task}"
    if not task_id.startswith(f"{suite}/"):
        _fail(ValueError("--suite and --task refer to different suites"))
    try:
        source_config = _source_config(
            suite_source,
            suite_variant,
            strict_compatibility=strict_compatibility,
        )
        if runtime == "docker":
            if docker_image is None:
                raise ValueError("--runtime docker requires --docker-image")
            docker_config = DockerRuntimeConfig(
                image=docker_image,
                pull_policy=docker_pull_policy,
                run_as_user=docker_user,
                memory_bytes=docker_memory_bytes,
                cpus=docker_cpus,
                pids_limit=docker_pids_limit,
                tmpfs_bytes=docker_tmpfs_bytes,
                stop_timeout_s=docker_stop_timeout_s,
                max_command_time_s=docker_max_command_time_s,
                environment_allowlist=docker_environment_allowlist or [],
            )
        else:
            if docker_image is not None:
                raise ValueError("--docker-image requires --runtime docker")
            docker_config = None
        config = RunConfig(
            task_id=task_id,
            mode=mode,
            agent=agent,
            model=model,
            model_options=ModelRunConfig(
                base_url=model_base_url,
                base_url_env=model_base_url_env,
                provider_id=model_provider_id,
                model_id=model_id,
                api_key_env=model_api_key_env,
                connect_timeout_s=model_connect_timeout_s,
                read_timeout_s=model_read_timeout_s,
                request_timeout_s=model_request_timeout_s,
                max_response_bytes=model_max_response_bytes,
                require_exact_model_id=model_require_exact_model_id,
                temperature=temperature,
                top_p=top_p,
                client_options=_plugin_options(model_option, flag="--model-option"),
            ),
            agent_options=_plugin_options(agent_option, flag="--agent-option"),
            max_invalid_actions=max_invalid_actions,
            suite_source=source_config,
            runtime=runtime,
            docker_config=docker_config,
            toolchain_profile=toolchain_profile,
            agent_ppa_feedback=agent_ppa_feedback,
            agent_ppa_max_calls=agent_ppa_max_calls,
            seed=seed,
            output=output,
        )
        registries = build_registries()
        _load_profile_file(
            registries,
            toolchain_profile_file,
            expected_id=toolchain_profile,
        )
        service = VeriGym(registries)
        if samples > 1 or pass_k:
            sample_result = service.run_samples(
                config,
                samples=samples,
                pass_k=pass_k or [1],
            )
            _print_sample_result(sample_result)
            if not sample_result.report.canonical_valid:
                raise typer.Exit(code=4)
            return
        result = service.run(config)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)
        return
    status = (
        "PASS"
        if result.scorecard.resolved
        else "ERROR"
        if result.scorecard.status == "error"
        else "FAIL"
    )
    style = "green" if status == "PASS" else "red"
    console.print(f"[{style}]{status}[/{style}] {result.scorecard.task_id}")
    console.print(f"Run directory: {result.run_dir}")
    console.print(f"Runtime isolation: {result.manifest.runtime.isolation_level}")
    console.print(
        f"Verifier: {result.scorecard.correctness.tests_passed or 0}/"
        f"{result.scorecard.correctness.tests_total or 0} tests; "
        f"termination={result.scorecard.termination_reason}"
    )
    if result.scorecard.resolved:
        return
    missing_dependency_categories = {"tool_not_found", "license_unavailable"}
    if any(
        verifier.error_category.value in missing_dependency_categories
        for verifier in result.scorecard.verifier_results
    ):
        raise typer.Exit(code=3)
    raise typer.Exit(code=4 if result.scorecard.status == "error" else 1)


@app.command("batch")
def batch(
    config_path: Path | None = typer.Option(
        None,
        "--config",
        help="Strict YAML/JSON experiment configuration.",
    ),
    resume_path: Path | None = typer.Option(
        None,
        "--resume",
        help="Resume an existing immutable experiment directory.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and print the complete frozen plan without child execution.",
    ),
    max_workers: int | None = typer.Option(
        None,
        "--max-workers",
        min=1,
        max=32,
        help="Override bounded local workers; recorded in the config identity.",
    ),
    fail_fast_infrastructure: bool = typer.Option(
        False,
        "--fail-fast-infrastructure",
        help="Stop scheduling after the first infrastructure failure.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Override the new experiment root; unavailable during resume.",
    ),
) -> None:
    """Plan or execute a deterministic experiment through ordinary core runs."""

    if config_path is None and resume_path is None:
        _fail(ValueError("batch requires --config or --resume"))
    if resume_path is not None and dry_run:
        _fail(ValueError("--dry-run cannot be combined with --resume"))
    if resume_path is not None and any(value is not None for value in (max_workers, output)):
        _fail(ValueError("resume does not permit plan-changing worker/output overrides"))
    if resume_path is not None and fail_fast_infrastructure:
        _fail(ValueError("resume does not permit a plan-changing fail-fast override"))
    try:
        supplied = load_experiment_config(config_path) if config_path is not None else None
        effective_config = supplied
        if effective_config is None and resume_path is not None:
            effective_config = load_json_model(
                resume_path / "experiment_config.json",
                ExperimentConfig,
            )

        def service_factory() -> VeriGym:
            registries = build_registries()
            if effective_config is not None:
                _load_profile_file(
                    registries,
                    effective_config.profile_file,
                    expected_id=effective_config.profile,
                )
            return VeriGym(registries)

        runner = BatchRunner(
            planner=ExperimentPlanner(service_factory()),
            service_factory=service_factory,
        )
        if resume_path is not None:
            result = runner.resume(resume_path, supplied_config=supplied)
        else:
            assert supplied is not None
            execution = supplied.execution
            if max_workers is not None:
                execution = execution.model_copy(update={"max_workers": max_workers})
            if fail_fast_infrastructure:
                execution = execution.model_copy(update={"continue_on_infrastructure_error": False})
            normalized = supplied.model_copy(
                update={
                    "execution": execution,
                    "output": (
                        supplied.output.model_copy(update={"root": output})
                        if output is not None
                        else supplied.output
                    ),
                }
            )
            plan = runner.planner.build(normalized)
            if dry_run:
                console.print_json(plan.model_dump_json(indent=2))
                console.print(f"Planned child runs: {len(plan.items)}")
                console.print(
                    f"Plan item limit: {normalized.execution.max_plan_items} (hard ceiling: 100000)"
                )
                return
            result = runner.run(plan)
        console.print(f"Experiment: {result.manifest.experiment_id}")
        console.print(f"Status: {result.state.status}")
        console.print(
            f"Child runs: {result.state.valid_terminal_count}/{result.state.planned_count}"
        )
        console.print(f"Experiment directory: {result.experiment_dir}")
        console.print(f"Aggregate: {result.experiment_dir / 'reports' / 'aggregate.json'}")
        if result.exit_code:
            raise typer.Exit(code=result.exit_code)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@app.command("replay")
def replay(
    run_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    verify: bool = typer.Option(
        False,
        "--verify",
        help="Re-run verifier-only stages on the frozen candidate; never calls an agent/model.",
    ),
) -> None:
    """Validate and display a stored visible episode."""

    try:
        summary = replay_run(run_dir, verify=verify)
    except Exception as exc:
        _fail(exc)
        return
    table = Table(title=f"Replay {summary.manifest.run_id}")
    table.add_column("Seq", justify="right")
    table.add_column("Event")
    table.add_column("Summary")
    for event in summary.events:
        detail = ""
        if event.event_type == "agent_action":
            detail = str(event.payload.get("type", ""))
        elif event.event_type == "tool_request":
            detail = str(event.payload.get("tool", ""))
        elif event.event_type == "tool_result":
            detail = f"{event.payload.get('tool', '')}: {event.payload.get('category', '')}"
        elif event.event_type == "verifier_node_result":
            detail = f"{event.payload.get('node_id', '')}: {event.payload.get('status', '')}"
        elif event.event_type == "episode_terminated":
            detail = f"resolved={event.payload.get('resolved')}"
        table.add_row(str(event.sequence), event.event_type, detail)
    console.print(table)
    console.print(
        f"Stored scorecard: resolved={summary.scorecard.resolved}, "
        f"status={summary.scorecard.status}"
    )
    if verify:
        console.print(f"Reverification: resolved={summary.reverified_resolved}")
        if not summary.reverified_resolved:
            raise typer.Exit(code=1)


@suites_app.command("list")
def suites_list() -> None:
    registries = build_registries()
    table = Table("Suite", "Version", "Description")
    for name, suite in registries.suites.items():
        table.add_row(name, suite.descriptor.suite_version, suite.descriptor.description)
    console.print(table)


@suites_app.command("inspect")
def suites_inspect(name: str) -> None:
    try:
        descriptor = build_registries().suites.get(name).descriptor
        console.print_json(descriptor.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@suites_app.command("validate")
def suites_validate(
    suite: str = typer.Option(..., "--suite"),
    source: Path = typer.Option(
        ...,
        "--source",
        help="External repository/dataset path; VeriGym never downloads benchmark data.",
    ),
    variant: str | None = typer.Option(None, "--variant"),
    strict_compatibility: bool = typer.Option(
        True,
        "--strict-compatibility/--no-strict-compatibility",
    ),
) -> None:
    """Validate an externally supplied suite source without modifying it."""

    try:
        adapter = (
            build_registries()
            .suites.get(suite)
            .with_source(
                SuiteSourceConfig(
                    source_root=source,
                    variant=variant,
                    strict_compatibility=strict_compatibility,
                )
            )
        )
        report = adapter.validate_source()
        console.print_json(report.model_dump_json(indent=2))
        if not report.valid:
            raise typer.Exit(code=2)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@tasks_app.command("list")
def tasks_list(
    suite: str = typer.Option(..., "--suite"),
    source: Path | None = typer.Option(
        None,
        "--source",
        help="External repository/dataset path; never auto-downloaded.",
    ),
    variant: str | None = typer.Option(None, "--variant"),
    strict_compatibility: bool = typer.Option(
        True,
        "--strict-compatibility/--no-strict-compatibility",
    ),
) -> None:
    try:
        adapter = build_registries().suites.get(suite)
        source_config = _source_config(
            source,
            variant,
            strict_compatibility=strict_compatibility,
        )
        if source_config is not None:
            adapter = adapter.with_source(source_config)
        table = Table("Task ID", "Native ID")
        for reference in adapter.discover():
            table.add_row(reference.id, reference.native_id)
        console.print(table)
    except Exception as exc:
        _fail(exc)


@tasks_app.command("show")
def tasks_show(
    task_id: str,
    source: Path | None = typer.Option(None, "--source"),
    variant: str | None = typer.Option(None, "--variant"),
) -> None:
    try:
        _suite, task, _assets = VeriGym().load_task(
            task_id,
            _source_config(source, variant, strict_compatibility=True),
        )
        console.print_json(task.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@tools_app.command("list")
def tools_list() -> None:
    registries = build_registries()
    table = Table("Tool", "Visibility", "Provider")
    for name, tool in registries.tools.items():
        table.add_row(name, tool.descriptor.visibility.value, tool.descriptor.provider)
    console.print(table)


@tools_app.command("check")
def tools_check(name: str) -> None:
    try:
        tool = build_registries().tools.get(name)
        health = tool.health_check()
        console.print_json(health.model_dump_json(indent=2))
        if not health.healthy:
            raise typer.Exit(code=3)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@profiles_app.command("list")
def profiles_list() -> None:
    table = Table("Profile", "Version", "Scope", "Reproducibility")
    for profile_id, profile in build_registries().profiles.items():
        scope = profile.metrics.scope if profile.metrics is not None else "execution-only"
        table.add_row(profile_id, profile.version, scope, profile.reproducibility_scope)
    console.print(table)


@profiles_app.command("show")
def profiles_show(
    profile_id: str,
    profile_file: Path | None = typer.Option(None, "--file", exists=True, dir_okay=False),
) -> None:
    try:
        registries = build_registries()
        _load_profile_file(registries, profile_file, expected_id=profile_id)
        profile = registries.profiles.get(profile_id)
        console.print_json(profile.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@profiles_app.command("validate")
def profiles_validate(
    profile_id: str,
    profile_file: Path | None = typer.Option(None, "--file", exists=True, dir_okay=False),
) -> None:
    try:
        registries = build_registries()
        _load_profile_file(registries, profile_file, expected_id=profile_id)
        profile = registries.profiles.get(profile_id)
        result = validate_profile(profile, _synthesis_backend(registries, profile))
        console.print_json(result.model_dump_json(indent=2))
        if not result.valid:
            raise typer.Exit(code=2)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@profiles_app.command("resolve")
def profiles_resolve(
    profile_id: str,
    runtime_name: str = typer.Option("docker", "--runtime"),
    docker_image: str | None = typer.Option(None, "--docker-image"),
    task_id: str | None = typer.Option(
        None,
        "--task",
        help="Task contract used for source/top/reference identity resolution.",
    ),
    profile_file: Path | None = typer.Option(None, "--file", exists=True, dir_okay=False),
) -> None:
    """Resolve exact tools/assets/runtime state; never invokes an agent or model."""

    runtime = None
    try:
        registries = build_registries()
        _load_profile_file(registries, profile_file, expected_id=profile_id)
        profile = registries.profiles.get(profile_id)
        selected_task = task_id or str(profile.metadata.get("acceptance_task", ""))
        if not selected_task:
            raise ValueError("profile resolution requires --task")
        service = VeriGym(registries)
        suite, task, _assets = service.load_task(selected_task)
        if runtime_name == "docker":
            if docker_image is None:
                raise ValueError("--runtime docker requires --docker-image")
            docker_config = DockerRuntimeConfig(image=docker_image, pull_policy="never")
        else:
            if docker_image is not None:
                raise ValueError("--docker-image requires --runtime docker")
            docker_config = None
        runtime = registries.runtimes.get(runtime_name).configure(docker_config)
        runtime.prepare(f"profile-resolve-{uuid.uuid4().hex[:12]}")
        reference = suite.reference_solution(task)
        resolved = resolve_toolchain_profile(
            profile,
            runtime,
            source_paths=list(task.workspace.entrypoints),
            top_module=profile.flow.top_module if profile.flow is not None else "",
            reference_candidate_hash=content_hash(reference) if reference is not None else None,
            backend=_synthesis_backend(registries, profile),
        )
        console.print_json(resolved.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)
    finally:
        if runtime is not None:
            runtime.close()


@report_app.command("compare")
def report_compare(
    run_a: Path = typer.Argument(..., exists=True, file_okay=False),
    run_b: Path = typer.Argument(..., exists=True, file_okay=False),
    metric: Literal["area", "delay", "worst_negative_slack", "power"] = typer.Option(
        "area", "--metric"
    ),
) -> None:
    """Rank two runs only when their full resolved metric contracts match."""

    try:
        result = (
            compare_area(run_a, run_b)
            if metric == "area"
            else compare_power(run_a, run_b)
            if metric == "power"
            else compare_timing(run_a, run_b, metric=metric)
        )
        console.print_json(result.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@report_app.command("generate")
def report_generate(
    root: Path = typer.Argument(..., exists=True, file_okay=False),
    format_name: Literal["json", "csv", "markdown"] = typer.Option(
        "json",
        "--format",
    ),
    output: Path = typer.Option(..., "--output"),
    group_by: list[str] | None = typer.Option(
        None,
        "--group-by",
        help="Safe grouping dimension; repeat to form a composite group.",
    ),
) -> None:
    """Generate one offline report without invoking models, tools, or runtimes."""

    try:
        generated = ReportService().generate_one(
            root,
            format_name=format_name,
            output=output,
            group_by=tuple(group_by or ["system"]),
        )
        console.print(f"Report: {generated}")
    except Exception as exc:
        _fail(exc)


@campaign_app.command("validate")
def campaign_validate(
    config_path: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        dir_okay=False,
    ),
) -> None:
    """Validate a campaign and all frozen inputs without writing reports."""

    try:
        report = CampaignService().build_from_path(config_path)
        console.print_json(report.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@campaign_app.command("generate")
def campaign_generate(
    config_path: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        dir_okay=False,
    ),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Write deterministic campaign JSON, CSV, and Markdown reports offline."""

    try:
        generated = CampaignService().generate_from_path(config_path, output_dir=output)
        console.print(f"Campaign JSON: {generated.json_path}")
        console.print(f"Campaign CSV: {generated.csv_path}")
        console.print(f"Campaign Markdown: {generated.markdown_path}")
    except Exception as exc:
        _fail(exc)


@trajectories_app.command("inspect")
def trajectories_inspect(
    source: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Inspect frozen run inputs without invoking a model, runtime, or verifier."""

    try:
        console.print_json(json.dumps(inspect_trajectory_source(source), sort_keys=True))
    except Exception as exc:
        _fail(exc)


@trajectories_app.command("export")
def trajectories_export(
    source: Path = typer.Argument(..., exists=True, file_okay=False),
    output: Path = typer.Option(..., "--output"),
    split_manifest_path: Path = typer.Option(
        ...,
        "--task-split",
        exists=True,
        dir_okay=False,
    ),
    agent_versions_path: Path = typer.Option(
        ...,
        "--agent-versions",
        exists=True,
        dir_okay=False,
    ),
    assignments_path: Path = typer.Option(
        ...,
        "--run-version-assignments",
        exists=True,
        dir_okay=False,
    ),
    source_commit: str = typer.Option(..., "--source-commit"),
    package_hash: list[str] | None = typer.Option(None, "--package-hash"),
) -> None:
    """Export canonical observable JSONL after validating all frozen inputs."""

    try:
        split = load_json_model(split_manifest_path, TaskSplitManifest)
        validate_task_split(split)
        versions = _load_version_set(agent_versions_path)
        assignments = load_json_model(assignments_path, RunAgentVersionAssignments)
        validate_run_version_assignments(assignments)
        run_versions: dict[str, str] = {}
        for assignment in assignments.assignments:
            version = versions.get(assignment.agent_version_id)
            if version is None or version.version_hash != assignment.agent_version_hash:
                raise ValueError("run/version assignment differs from the frozen version set")
            run_versions[assignment.run_id] = assignment.agent_version_id
        result = TrajectoryExporter().export(
            source,
            output,
            split_manifest=split,
            agent_versions=versions,
            run_agent_versions=run_versions,
            source_commit=source_commit,
            package_identities=_named_hashes(
                package_hash or [],
                flag="--package-hash",
            ),
        )
        console.print_json(result.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@trajectories_app.command("validate")
def trajectories_validate(
    dataset: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Validate a sealed trajectory dataset with zero external calls."""

    try:
        result = validate_trajectory_dataset(dataset)
        console.print_json(result.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@trajectories_app.command("replay")
def trajectories_replay(
    dataset: Path = typer.Argument(..., exists=True, file_okay=False),
    source: Path = typer.Option(..., "--source", exists=True, file_okay=False),
) -> None:
    """Recompute source, artifact, and reward bindings with zero external calls."""

    try:
        result = replay_trajectory_dataset(dataset, source)
        console.print_json(result.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@evolve_app.command("prepare-training-data")
def evolve_prepare_training_data(
    dataset: Path = typer.Argument(..., exists=True, file_okay=False),
    output: Path = typer.Option(..., "--output"),
) -> None:
    """Derive the task-free memory-builder input from eligible training runs."""

    try:
        dataset_manifest = validate_trajectory_dataset(dataset)
        split = load_json_model(dataset / "task-split-manifest.json", TaskSplitManifest)
        trajectories = load_jsonl_models(dataset / "trajectories.jsonl", EpisodeTrajectory)
        summary = prepare_training_summary(
            trajectories,
            split_manifest_hash=split.manifest_hash,
            trajectory_dataset_hash=dataset_manifest.dataset_hash,
        )
        atomic_dump_json(output, summary)
        console.print_json(summary.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@evolve_app.command("validate-memory")
def evolve_validate_memory(
    memory_path: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Validate the code-free, task-independent frozen memory pack."""

    try:
        memory = load_json_model(memory_path, MemoryPack)
        validate_memory_pack(memory)
        console.print_json(memory.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@evolve_app.command("inspect-agent-version")
def evolve_inspect_agent_version(
    version_path: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Validate and display one immutable agent version."""

    try:
        version = load_json_model(version_path, AgentVersionManifest)
        validate_agent_version(version)
        console.print_json(version.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@evolve_app.command("build-context-version")
def evolve_build_context_version(
    parent_path: Path = typer.Option(..., "--parent", exists=True, dir_okay=False),
    dataset: Path = typer.Option(..., "--dataset", exists=True, file_okay=False),
    summary_path: Path = typer.Option(..., "--training-summary", exists=True, dir_okay=False),
    memory_path: Path = typer.Option(..., "--memory-pack", exists=True, dir_okay=False),
    memory_builder_identity_hash: str = typer.Option(..., "--memory-builder-identity-hash"),
    memory_builder_input_hash: str = typer.Option(..., "--memory-builder-input-hash"),
    memory_builder_output_hash: str = typer.Option(..., "--memory-builder-output-hash"),
    process_ledger_hash: str = typer.Option(..., "--process-ledger-hash"),
    output: Path = typer.Option(..., "--output"),
) -> None:
    """Freeze v1 and its update record after successful real memory synthesis."""

    try:
        parent = load_json_model(parent_path, AgentVersionManifest)
        dataset_manifest = validate_trajectory_dataset(dataset)
        summary = load_json_model(summary_path, SanitizedTrainingSummary)
        memory = load_json_model(memory_path, MemoryPack)
        version, update = freeze_context_update(
            parent=parent,
            dataset=dataset_manifest,
            training_summary=summary,
            memory_pack=memory,
            memory_builder_identity_hash=memory_builder_identity_hash,
            memory_builder_input_hash=memory_builder_input_hash,
            memory_builder_output_hash=memory_builder_output_hash,
            process_ledger_hash=process_ledger_hash,
        )
        if output.exists() and (
            output.is_symlink() or not output.is_dir() or any(output.iterdir())
        ):
            raise ValueError("--output must be a new or empty real directory")
        output.mkdir(parents=True, exist_ok=True)
        atomic_dump_json(output / "agent-version-v1.json", version)
        atomic_dump_json(output / "agent-update.json", update)
        console.print_json(version.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@evolve_app.command("replay-context-update")
def evolve_replay_context_update(
    parent_path: Path = typer.Option(..., "--parent", exists=True, dir_okay=False),
    result_path: Path = typer.Option(..., "--result", exists=True, dir_okay=False),
    update_path: Path = typer.Option(..., "--update", exists=True, dir_okay=False),
    dataset: Path = typer.Option(..., "--dataset", exists=True, file_okay=False),
    summary_path: Path = typer.Option(..., "--training-summary", exists=True, dir_okay=False),
    memory_path: Path = typer.Option(..., "--memory-pack", exists=True, dir_okay=False),
) -> None:
    """Replay version creation using frozen hashes and no memory-builder call."""

    try:
        replay_context_update(
            parent=load_json_model(parent_path, AgentVersionManifest),
            result=load_json_model(result_path, AgentVersionManifest),
            update=load_json_model(update_path, AgentUpdateManifest),
            dataset=validate_trajectory_dataset(dataset),
            training_summary=load_json_model(summary_path, SanitizedTrainingSummary),
            memory_pack=load_json_model(memory_path, MemoryPack),
        )
        console.print("Context update replay: VALID (zero external calls)")
    except Exception as exc:
        _fail(exc)


@evolve_app.command("scan-contamination")
def evolve_scan_contamination(
    split_manifest_path: Path = typer.Option(
        ...,
        "--task-split",
        exists=True,
        dir_okay=False,
    ),
    training_root: list[str] | None = typer.Option(None, "--training-root"),
    heldout_root: list[str] | None = typer.Option(None, "--heldout-root"),
    memory_path: Path | None = typer.Option(None, "--memory-pack", dir_okay=False),
    output: Path = typer.Option(..., "--output"),
) -> None:
    """Scan a frozen split after v1 exists; output identities, never asset contents."""

    try:
        split = load_json_model(split_manifest_path, TaskSplitManifest)
        memory = load_json_model(memory_path, MemoryPack) if memory_path is not None else None
        scan = scan_contamination(
            split_manifest=split,
            training_roots=_named_paths(training_root or [], flag="--training-root"),
            heldout_roots=_named_paths(heldout_root or [], flag="--heldout-root"),
            memory_pack=memory,
        )
        validate_contamination_scan(scan)
        atomic_dump_json(output, scan)
        console.print_json(scan.model_dump_json(indent=2))
        if not scan.passed:
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@evolve_app.command("compare")
def evolve_compare(
    experiment: Path = typer.Argument(..., exists=True, file_okay=False),
    split_manifest_path: Path = typer.Option(
        ...,
        "--task-split",
        exists=True,
        dir_okay=False,
    ),
    baseline_version_id: str = typer.Option(..., "--baseline-version"),
    evolved_version_id: str = typer.Option(..., "--evolved-version"),
    output: Path = typer.Option(..., "--output"),
) -> None:
    """Produce deterministic separate v0/v1 metrics and paired differences."""

    try:
        report = build_evolving_evaluation(
            experiment,
            split_manifest=load_json_model(split_manifest_path, TaskSplitManifest),
            baseline_version_id=baseline_version_id,
            evolved_version_id=evolved_version_id,
        )
        atomic_dump_json(output, report)
        console.print_json(report.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@agents_app.command("list")
def agents_list() -> None:
    registries = build_registries()
    table = Table("Agent harness", "Modes", "Model required", "Provider")
    for name, agent_plugin in registries.agents.items():
        modes = ",".join(sorted(mode.value for mode in agent_plugin.supported_modes))
        table.add_row(
            name,
            modes,
            "yes" if agent_plugin.requires_model else "no",
            agent_plugin.descriptor.provider,
        )
    console.print(table)


@agents_app.command("inspect")
def agents_inspect(name: str) -> None:
    try:
        agent_plugin = build_registries().agents.get(name)
        console.print_json(
            data={
                "descriptor": agent_plugin.descriptor.model_dump(mode="json"),
                "supported_modes": sorted(mode.value for mode in agent_plugin.supported_modes),
                "requires_model": agent_plugin.requires_model,
            }
        )
    except Exception as exc:
        _fail(exc)


@models_app.command("list")
def models_list() -> None:
    registries = build_registries()
    table = Table("Model client", "Provider", "Offline")
    for name, model_plugin in registries.models.items():
        descriptor = model_plugin.descriptor
        table.add_row(
            name,
            descriptor.provider,
            "yes" if "offline" in descriptor.capabilities else "no/optional",
        )
    console.print(table)


@models_app.command("inspect")
def models_inspect(name: str) -> None:
    try:
        descriptor = build_registries().models.get(name).descriptor
        console.print_json(descriptor.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
