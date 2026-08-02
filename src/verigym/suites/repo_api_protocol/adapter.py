"""Provider-neutral repository action-protocol conformance suite."""

from __future__ import annotations

from pathlib import Path

from verigym.schemas.base import PLUGIN_API_VERSION, SCHEMA_VERSION
from verigym.schemas.common import SuiteDescriptor
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite


class RepositoryApiProtocolSuite(RepositoryRtlSuite):
    """Independent Apache-2.0 fixtures for ``repository_action.v2``."""

    descriptor = SuiteDescriptor(
        schema_version=SCHEMA_VERSION,
        name="repo-api-protocol",
        version="0.1.0",
        api_version=PLUGIN_API_VERSION,
        provider="verigym",
        capabilities=[
            "repository_repair",
            "multi_file_patch",
            "trusted_public_tests",
            "hidden_regression",
            "action_protocol_conformance",
            "conformance",
        ],
        title="VeriGym provider-neutral repository action protocol",
        description=(
            "Independent repository fixtures for strict multi-turn API-agent protocol testing."
        ),
        suite_version="0.1.0",
        license="Apache-2.0",
    )
    _PACKAGED_ASSETS_ROOT = Path(__file__).parent / "assets"
    _EXPECTED_PACKAGED_TASK_IDS = frozenset(
        {
            "repo-api-protocol/protocol-dual-fix",
            "repo-api-protocol/protocol-pipeline-flush",
            "repo-api-protocol/protocol-valid-hold",
        }
    )
    _SOURCE_VARIANT = "repo-api-protocol-v1"
    _SOURCE_ROOT_LABEL = "<external-repo-api-protocol-source>"
    _NATIVE_LAYOUT = "repo_api_protocol_task_bundles_v1"
    _HELDOUT_ASSETS_ROOT = None


__all__ = ["RepositoryApiProtocolSuite"]
