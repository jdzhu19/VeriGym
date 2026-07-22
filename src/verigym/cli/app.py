"""VeriGym command-line interface for toy RTL and external VerilogEval V2."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Literal

import typer
from rich.console import Console
from rich.table import Table

from verigym.core.errors import VeriGymError
from verigym.core.hashing import content_hash
from verigym.core.orchestrator import VeriGym
from verigym.core.replay import replay_run
from verigym.profiles.comparison import compare_area
from verigym.profiles.resolver import resolve_toolchain_profile
from verigym.profiles.validation import validate_profile
from verigym.registry.collections import build_registries
from verigym.runtimes.docker.diagnostics import diagnose_docker
from verigym.schemas.common import InteractionMode
from verigym.schemas.model import ModelRunConfig
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig
from verigym.schemas.sampling import SampleSetResult
from verigym.schemas.suite import SuiteSourceConfig
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
report_app = typer.Typer(help="Strict comparison commands for compatible ranked metrics.")
app.add_typer(suites_app, name="suites")
app.add_typer(tasks_app, name="tasks")
app.add_typer(tools_app, name="tools")
app.add_typer(agents_app, name="agents")
app.add_typer(models_app, name="models")
app.add_typer(profiles_app, name="profiles")
app.add_typer(report_app, name="report")
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
) -> None:
    """Report package, runtime, and tool health without printing secrets."""

    try:
        registries = build_registries()
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
    abc = local_abc_health()
    table.add_row("tool:yosys-abc", "ok" if abc.healthy else "missing", abc.message)
    for profile_id, profile in registries.profiles.items():
        validation = validate_profile(profile)
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
    temperature: float = typer.Option(0.0, "--temperature", min=0.0),
    top_p: float | None = typer.Option(None, "--top-p", min=0.000000001, max=1.0),
    max_invalid_actions: int = typer.Option(3, "--max-invalid-actions", min=1),
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
                model_id=model_id,
                api_key_env=model_api_key_env,
                connect_timeout_s=model_connect_timeout_s,
                read_timeout_s=model_read_timeout_s,
                request_timeout_s=model_request_timeout_s,
                temperature=temperature,
                top_p=top_p,
            ),
            max_invalid_actions=max_invalid_actions,
            suite_source=source_config,
            runtime=runtime,
            docker_config=docker_config,
            toolchain_profile=toolchain_profile,
            seed=seed,
            output=output,
        )
        service = VeriGym()
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
def profiles_show(profile_id: str) -> None:
    try:
        profile = build_registries().profiles.get(profile_id)
        console.print_json(profile.model_dump_json(indent=2))
    except Exception as exc:
        _fail(exc)


@profiles_app.command("validate")
def profiles_validate(profile_id: str) -> None:
    try:
        profile = build_registries().profiles.get(profile_id)
        result = validate_profile(profile)
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
) -> None:
    """Resolve exact tools/assets/runtime state; never invokes an agent or model."""

    runtime = None
    try:
        registries = build_registries()
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
    metric: Literal["area"] = typer.Option("area", "--metric"),
) -> None:
    """Rank two runs only when their full resolved area contracts match."""

    del metric
    try:
        result = compare_area(run_a, run_b)
        console.print_json(result.model_dump_json(indent=2))
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
