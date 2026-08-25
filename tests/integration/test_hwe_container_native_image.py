from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

RUN_HWE_IMAGE = os.environ.get("VERIGYM_RUN_CVA6_HWE_AGENT_IMAGE_TESTS") == "1"
HWE_IMAGE_ID = os.environ.get("VERIGYM_CVA6_HWE_AGENT_IMAGE_ID")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.skipif(
        not RUN_HWE_IMAGE,
        reason="set VERIGYM_RUN_CVA6_HWE_AGENT_IMAGE_TESTS=1 for the HWE image test",
    ),
]


def test_cva6_hwe_v2_image_has_container_native_reads_and_isolated_writes() -> None:
    if not HWE_IMAGE_ID or not HWE_IMAGE_ID.startswith("sha256:"):
        pytest.fail("VERIGYM_CVA6_HWE_AGENT_IMAGE_ID must select one immutable local image ID")
    if os.getuid() == 0 or os.getgid() == 0:
        pytest.fail("the HWE image test must run from a non-root host account")

    inspected = subprocess.run(
        ["docker", "image", "inspect", HWE_IMAGE_ID],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    image = json.loads(inspected.stdout)[0]
    assert image["Id"] == HWE_IMAGE_ID
    labels = image["Config"]["Labels"]
    assert labels["org.verigym.collection.profile"] == "hwe_standard_v2"
    assert labels["org.verigym.tool.contract"] == "hwe_native_shell_v2"
    assert labels["org.verigym.provider_credentials"] == "absent"
    assert labels["org.verigym.hidden_assets"] == "absent"
    assert labels["org.verigym.reference_patch"] == "absent"
    assert labels["org.verigym.verifier_payload"] == "absent"

    scratch_parent = Path("/data/jzhu484/Agent/.verigym-tmp")
    scratch_parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="hwe-image-test.", dir=scratch_parent))
    try:
        command = "\n".join(
            (
                "set -eu",
                'test "$(id -u)" != 0',
                'test "$(ls /sys/class/net)" = lo',
                "test -d /home/cva6",
                'test -z "$(find /home/cva6 -mindepth 1 -maxdepth 1 -print -quit)"',
                "test ! -e /workspace/verifier",
                "test ! -e /hidden-verifier",
                "test ! -e /reference.patch",
                "if touch /verigym-rootfs-write 2>/dev/null; then exit 41; fi",
                "touch /workspace/repository/candidate-write",
                "touch /tmp/ephemeral-write",
                "find .. -maxdepth 2 -print >/tmp/find-output",
                "grep -q ../repository /tmp/find-output",
                "sed -n '1p' /etc/os-release >/tmp/os-release",
                "rg --version >/tmp/rg-version",
                "make --version >/tmp/make-version",
                "verilator --version >/tmp/verilator-version",
            )
        )
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "4096",
                "--memory",
                "16g",
                "--cpus",
                "4",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--env",
                "VERILATOR_ROOT=/tools/verilator",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=1073741824,mode=1777",
                "--mount",
                f"type=bind,src={workspace},dst=/workspace/repository",
                HWE_IMAGE_ID,
                "/bin/bash",
                "-lc",
                command,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, completed.stderr[-4000:]
        assert (workspace / "candidate-write").is_file()
        assert not (workspace / "ephemeral-write").exists()
    finally:
        shutil.rmtree(workspace)
