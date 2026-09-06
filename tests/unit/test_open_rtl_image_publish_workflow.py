from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/publish-open-rtl-images.yml"


def _workflow() -> dict[str, object]:
    payload = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(payload, dict)
    return payload


def test_open_rtl_publish_workflow_has_a_minimal_trusted_trigger() -> None:
    payload = _workflow()
    assert payload["permissions"] == {"contents": "read", "packages": "write"}
    trigger = payload["on"]
    assert isinstance(trigger, dict)
    assert set(trigger) == {"push", "workflow_dispatch"}
    push = trigger["push"]
    assert isinstance(push, dict)
    assert push["branches"] == ["agent/publish-qualified-rtl-images"]

    source = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" not in source
    assert "secrets.GITHUB_TOKEN" in source
    assert re.findall(r"uses: [^\s]+@([0-9a-f]{40})", source)
    assert not re.findall(r"uses: [^\s]+@(?![0-9a-f]{40}(?:\s|$))[^\s]+", source)


def test_open_rtl_publish_workflow_excludes_codex_and_commercial_tools() -> None:
    payload = _workflow()
    jobs = payload["jobs"]
    assert isinstance(jobs, dict)
    publish = jobs["publish"]
    assert isinstance(publish, dict)
    strategy = publish["strategy"]
    assert isinstance(strategy, dict)
    matrix = strategy["matrix"]
    assert isinstance(matrix, dict)
    include = matrix["include"]
    assert isinstance(include, list)
    assert {item["package"] for item in include} == {
        "verigym-open-rtl-tools",
        "verigym-rtl-iverilog",
    }
    serialized = WORKFLOW.read_text(encoding="utf-8").lower()
    for forbidden in ("codex-repository-agent", "synopsys", "vcs", "design compiler"):
        assert forbidden not in serialized


def test_public_image_builds_are_attested_and_refuse_tag_replacement() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "--provenance=mode=max",
        "--sbom=true",
        "refusing to replace existing release tag",
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "@${DIGEST}",
    ):
        assert required in source
    assert ":latest" not in source


def test_public_image_contexts_exclude_repository_content_and_bundle_sources() -> None:
    expected_ignores = {
        "docker/iverilog12/.dockerignore": {"**", "!Dockerfile", "!README.md"},
        "docker/open-rtl-tools-opensta/.dockerignore": {
            "*",
            "!Dockerfile",
            "!README.md",
            "!SOURCE_IDENTITIES",
        },
    }
    for relative, expected in expected_ignores.items():
        observed = {
            line.strip()
            for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        assert observed == expected

    iverilog = (ROOT / "docker/iverilog12/Dockerfile").read_text(encoding="utf-8")
    combined = (ROOT / "docker/open-rtl-tools-opensta/Dockerfile").read_text(encoding="utf-8")
    assert "/usr/share/licenses/iverilog/COPYING" in iverilog
    assert "/usr/share/verigym/sources/iverilog-source.tar.gz" in iverilog
    for marker in (
        "/usr/share/licenses/cudd/LICENSE",
        "/usr/share/licenses/iverilog/COPYING",
        "/usr/share/licenses/opensta/LICENSE",
        "/usr/share/licenses/yosys/COPYING",
        "/usr/share/verigym/sources/cudd-3.0.0.tar.gz",
        "/usr/share/verigym/sources/opensta.tar.gz",
        "/usr/share/verigym/sources/yosys-v0.67.tar.gz",
    ):
        assert marker in combined
