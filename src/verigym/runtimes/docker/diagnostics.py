"""Credential-free Docker health and configured-image diagnostics."""

from __future__ import annotations

import uuid

from verigym.runtimes.docker.cleanup import inspect_owned_resources
from verigym.runtimes.docker.engine import DockerCliEngine
from verigym.runtimes.docker.errors import DockerRuntimeError
from verigym.runtimes.docker.image import inspect_backend
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.base import StrictModel
from verigym.schemas.runtime import DockerRuntimeConfig


class DockerDiagnostic(StrictModel):
    component: str
    healthy: bool
    message: str


def diagnose_docker(image: str | None = None) -> list[DockerDiagnostic]:
    """Inspect only; never build or pull an image and never print environment values."""

    engine = DockerCliEngine()
    diagnostics = [
        DockerDiagnostic(
            component="runtime:docker",
            healthy=engine.executable is not None,
            message=(
                "Docker CLI backend selected"
                if engine.executable
                else "Docker CLI is missing; install it or continue with --runtime local"
            ),
        )
    ]
    if engine.executable is None:
        return diagnostics
    try:
        backend, _info = inspect_backend(engine)
        diagnostics.extend(
            [
                DockerDiagnostic(
                    component="docker:daemon",
                    healthy=True,
                    message=(
                        f"client={backend.client_version}, server={backend.server_version}, "
                        f"api={backend.api_version}"
                    ),
                ),
                DockerDiagnostic(
                    component="docker:platform",
                    healthy=True,
                    message=(
                        f"{backend.server_os}/{backend.server_architecture}; "
                        f"rootless={backend.rootless}"
                    ),
                ),
                DockerDiagnostic(
                    component="docker:controls",
                    healthy=True,
                    message=(
                        "memory, swap, CPU, PID, network, and security controls are requestable"
                    ),
                ),
            ]
        )
        owned = inspect_owned_resources(engine)
        diagnostics.append(
            DockerDiagnostic(
                component="docker:stale-resources",
                healthy=not owned.container_ids and not owned.volume_names,
                message=(
                    f"managed containers={len(owned.container_ids)}, "
                    f"managed volumes={len(owned.volume_names)}"
                ),
            )
        )
    except DockerRuntimeError as exc:
        diagnostics.append(
            DockerDiagnostic(
                component="docker:daemon",
                healthy=False,
                message=(f"{exc}; start or configure the Docker daemon and verify user permission"),
            )
        )
        engine.close()
        return diagnostics
    engine.close()
    if image is None:
        diagnostics.append(
            DockerDiagnostic(
                component="docker:image",
                healthy=True,
                message=(
                    "not configured; pass --docker-image to inspect a prebuilt local image "
                    "(doctor never pulls or builds)"
                ),
            )
        )
        return diagnostics
    runtime = DockerRuntime(DockerRuntimeConfig(image=image, pull_policy="never"))
    try:
        runtime.prepare(f"doctor-{uuid.uuid4().hex[:12]}")
        descriptor = runtime.descriptor
        assert descriptor.image is not None and descriptor.security is not None
        diagnostics.extend(
            [
                DockerDiagnostic(
                    component="docker:image",
                    healthy=True,
                    message=(
                        f"id={descriptor.image.resolved_image_id}, "
                        f"platform={descriptor.image.os}/{descriptor.image.architecture}"
                    ),
                ),
                DockerDiagnostic(
                    component="docker:user",
                    healthy=descriptor.image.observed_uid not in {None, 0},
                    message=(
                        f"uid={descriptor.image.observed_uid}, gid={descriptor.image.observed_gid}"
                    ),
                ),
                DockerDiagnostic(
                    component="docker:iverilog",
                    healthy=descriptor.image.iverilog_version is not None,
                    message=(
                        f"{descriptor.image.iverilog_version}; "
                        f"compatibility={descriptor.image.compatibility_status}"
                    ),
                ),
                DockerDiagnostic(
                    component="docker:vvp",
                    healthy=descriptor.image.vvp_version is not None,
                    message=str(descriptor.image.vvp_version),
                ),
            ]
        )
    except DockerRuntimeError as exc:
        diagnostics.append(
            DockerDiagnostic(
                component="docker:image",
                healthy=False,
                message=(
                    f"{exc}; build or inspect the image explicitly and verify its non-root "
                    "user and Icarus installation"
                ),
            )
        )
    finally:
        runtime.close()
    return diagnostics


__all__ = ["DockerDiagnostic", "diagnose_docker"]
