"""Non-destructive inspection of uniquely labeled VeriGym Docker resources."""

from __future__ import annotations

from verigym.runtimes.docker.engine import DockerEngine
from verigym.schemas.base import StrictModel


class OwnedDockerResources(StrictModel):
    container_ids: list[str]
    volume_names: list[str]


def inspect_owned_resources(engine: DockerEngine) -> OwnedDockerResources:
    """List resources only; Milestone 7 intentionally has no global janitor."""

    return OwnedDockerResources(
        container_ids=engine.list_managed_containers(),
        volume_names=engine.list_managed_volumes(),
    )


__all__ = ["OwnedDockerResources", "inspect_owned_resources"]
