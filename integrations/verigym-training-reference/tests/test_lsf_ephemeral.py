from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from verigym_training_reference.lsf_ephemeral import (
    EphemeralLsfGpuRequest,
    build_bsub_command,
    submit_ephemeral_lsf_gpu_job,
)


def _request(tmp_path: Path) -> EphemeralLsfGpuRequest:
    experiments = tmp_path / "experiments"
    experiments.mkdir(exist_ok=True)
    return EphemeralLsfGpuRequest(
        job_name="hwe-sft-probe",
        queue="gpu",
        gpu_count=4,
        cpu_slots=16,
        wall_minutes=90,
        working_directory=tmp_path,
        output_directory=experiments / "submission",
        command=("python", "-m", "verigym_training_reference.probe"),
    )


def test_bsub_payload_is_noninteractive_and_shell_free(tmp_path: Path) -> None:
    command = build_bsub_command(_request(tmp_path))

    assert command[:3] == ["bsub", "-q", "gpu"]
    assert "-I" not in command and "-Is" not in command
    assert "bash" not in command and "sh" not in command
    assert "num=4:mode=shared:mps=no:j_exclusive=yes:gvendor=nvidia" in command
    assert command[-3:] == ["python", "-m", "verigym_training_reference.probe"]


@pytest.mark.parametrize("shell", ["bash", "/bin/sh", "zsh"])
def test_shell_payloads_are_rejected(tmp_path: Path, shell: str) -> None:
    request = _request(tmp_path)
    changed = EphemeralLsfGpuRequest(**{**request.__dict__, "command": (shell,)})

    with pytest.raises(ValueError, match="shell jobs are forbidden"):
        build_bsub_command(changed)


def test_submission_writes_secret_free_auto_exit_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(
            args=[], returncode=0, stdout="Job <501234> is submitted\n", stderr=""
        )

    monkeypatch.setattr("verigym_training_reference.lsf_ephemeral.subprocess.run", fake_run)

    receipt = submit_ephemeral_lsf_gpu_job(_request(tmp_path))

    assert receipt["job_id"] == "501234"
    assert receipt["interactive"] is False
    assert receipt["shell_payload"] is False
    assert receipt["persistent_allocation"] is False
    assert receipt["auto_exit_on_payload_completion"] is True
    assert receipt["payload_arguments_persisted"] is False
    persisted = json.loads(
        (tmp_path / "experiments/submission/lsf-submission-receipt.json").read_text()
    )
    assert persisted == receipt
