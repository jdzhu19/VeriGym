from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from scripts.analyze_hwe_observation_masking import analyze_transcripts
from scripts.collect_cva6_hwe_codex import (
    _action_conditioned_status,
    _load_startup_restarts,
    _materialization_rejection,
    _model_action_rejection,
    _startup_restart_record,
    _status,
    _write_startup_restarts,
    _zero_call_startup_restart_eligible,
)
from verigym.core.hashing import content_hash
from verigym.hwe.campaign import (
    HWE_CODEX_BASE_INSTRUCTION_POLICY,
    HWE_CODEX_PROMPT_CONTRACT_ID,
    HWE_CODEX_PROMPT_CONTRACT_VERSION,
    HWE_PILOT_TASKS,
    HweActionConditionedCampaignAttempt,
    HweActionConditionedCampaignState,
    HweCampaignAttempt,
    HweCampaignState,
)
from verigym.hwe.codex_collector import HweExecProtocolCollector
from verigym.hwe.codex_normalization import (
    HweCausalValidationError,
    normalize_codex_hwe_events,
)
from verigym.hwe.history_masking import (
    HWE_ACTION_CONDITIONED_DATASET_FORMAT,
    HWE_ACTION_CONDITIONED_SFT_FORMAT,
    HWE_HISTORY_MASKING_POLICY_ID,
    HWE_LOSSLESS_HISTORY_POLICY_ID,
    HweHistoryMaskingPolicy,
    build_hwe_action_conditioned_dataset_manifest,
    derive_hwe_lossless_history_view,
    derive_hwe_masked_history_views,
    materialize_hwe_action_conditioned_examples,
    summarize_hwe_masking_views,
    validate_hwe_action_conditioned_example,
)
from verigym.hwe.image_lock import build_hwe_agent_image_lock
from verigym.hwe.observation import HweObservationCompactor, structural_view
from verigym.hwe.private_audit import HweRawArtifactWriter
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_STANDARD_V1,
    HWE_STANDARD_V2,
    canonical_hwe_action_json,
    hwe_tool_contract_hash,
    hwe_tool_definitions,
    resolve_hwe_collection_profile,
)
from verigym.hwe.trajectory import (
    HweEpisodeBudget,
    HweLimitExceeded,
    HweNormalizedEvent,
    build_hwe_teacher_transcript,
    secondary_sft_compaction,
    validate_hwe_teacher_transcript,
)
from verigym.runtimes.docker.external_process import _normalize_app_server_notification


class CharacterCounter:
    tokenizer_id = "tiktoken-0.7.0/o200k_base"
    tokenizer_hash = hashlib.sha256(b"tiktoken==0.7.0\x00o200k_base").hexdigest()

    def count(self, text: str) -> int:
        return len(text)


def test_hwe_profiles_are_isolated_fixed_and_shell_arguments_fail_closed() -> None:
    profile = resolve_hwe_collection_profile("hwe_standard_v1")
    assert profile is HWE_STANDARD_V1
    assert profile.memory_bytes == 16 * 1024**3
    assert profile.episode_wall_time_s == 3600
    assert [item["function"]["name"] for item in hwe_tool_definitions()] == [
        "list_files",
        "read_file",
        "apply_patch",
        "shell",
        "inspect_diff",
        "finish",
    ]
    envelope = json.loads(canonical_hwe_action_json("shell", {"command": "rg counter rtl"}))
    assert envelope["protocol"] == "repository_action.v2"
    assert set(envelope["arguments"]) == {"command"}
    for command in ("FOO=bar make", "cat /etc/passwd", "cat ../hidden", "echo $HOME"):
        with pytest.raises(ValueError):
            canonical_hwe_action_json("shell", {"command": command})
    for command in (
        "rg -n 'assign result = source' repository/core/decoder.sv",
        r"rg -n '\$error|CVA6Cfg.XLEN == 64' repository/core/decoder.sv",
        r"printf '%s' '\$HOME'",
    ):
        assert (
            json.loads(canonical_hwe_action_json("shell", {"command": command}))["arguments"][
                "command"
            ]
            == command
        )
    for command, message in (
        ("FOO=bar make", "environment assignment"),
        ('echo "$HOME"', "environment expansion"),
        ("cat /etc/passwd", "absolute path"),
        ("cat ../hidden", "escaping path"),
    ):
        with pytest.raises(ValueError, match=message):
            canonical_hwe_action_json("shell", {"command": command})
    with pytest.raises(ValueError):
        canonical_hwe_action_json("shell", {"command": "make", "timeout": 900})


def test_hwe_v1_contract_and_profile_hashes_remain_frozen() -> None:
    assert hwe_tool_contract_hash() == (
        "1328c91ed4518c8380184432cc9bbdb2564cd1b3353c6ff97cd2660a647d31cd"
    )
    assert content_hash(HWE_STANDARD_V1.identity()) == (
        "cc4a3e3fa77b1eb558dcfba571ce63fdfb292db62bfe07e6818befce9619af6e"
    )
    action = canonical_hwe_action_json("shell", {"command": "rg counter rtl"})
    assert action == (
        '{"action":"shell","arguments":{"command":"rg counter rtl"},'
        '"protocol":"repository_action.v2"}'
    )


def test_hwe_v2_allows_container_native_reads_without_widening_other_tools() -> None:
    profile = resolve_hwe_collection_profile(HWE_COLLECTION_PROFILE_V2_ID)
    assert profile is HWE_STANDARD_V2
    assert profile.observation_policy_id == "hwe_repository_observation_v2"
    assert profile.tool_contract_id == "hwe_native_shell_v2"
    assert hwe_tool_contract_hash(profile_id=profile.profile_id) != hwe_tool_contract_hash()
    for command in (
        "find .. -maxdepth 2 -print | sort",
        "cd .. && find repository -maxdepth 2 -print",
        "sed -n '1,40p' /workspace/repository/TASK.md",
        "find /opt -maxdepth 2 -type f",
        "cat /etc/os-release",
        "rg if=bar bs=0 count=1 status=ok",
        'for f in rtl/*.sv; do test -f "$f"; done',
    ):
        envelope = json.loads(
            canonical_hwe_action_json(
                "shell", {"command": command}, profile_id=HWE_COLLECTION_PROFILE_V2_ID
            )
        )
        assert envelope["arguments"]["command"] == command
    for command in (
        "FOO=bar make",
        "echo ok; FOO=bar make",
        "env FOO=bar make",
        "echo $HOME",
    ):
        with pytest.raises(ValueError):
            canonical_hwe_action_json(
                "shell", {"command": command}, profile_id=HWE_COLLECTION_PROFILE_V2_ID
            )
    for command in (
        'test "$PWD" = /workspace/repository',
        'echo "$RISCV"',
        'test -d "${VERILATOR_ROOT}"',
    ):
        canonical_hwe_action_json(
            "shell", {"command": command}, profile_id=HWE_COLLECTION_PROFILE_V2_ID
        )
    with pytest.raises(ValueError):
        canonical_hwe_action_json(
            "shell",
            {"command": 'echo "$OLDPWD"'},
            profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        )
    with pytest.raises(ValueError):
        canonical_hwe_action_json(
            "shell",
            {"command": 'echo "$AWS_SECRET_ACCESS_KEY"'},
            profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        )
    with pytest.raises(ValueError):
        canonical_hwe_action_json(
            "shell",
            {"command": 'for f in "$HOME"; do echo "$f"; done'},
            profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        )
    python_heredoc = "python - <<PY\npath='rtl/top.sv'\nend=20\nprint(path, end)\nPY"
    envelope = json.loads(
        canonical_hwe_action_json(
            "shell", {"command": python_heredoc}, profile_id=HWE_COLLECTION_PROFILE_V2_ID
        )
    )
    assert envelope["arguments"]["command"] == python_heredoc
    with pytest.raises(ValueError, match="environment expansion"):
        canonical_hwe_action_json(
            "shell",
            {"command": "python - <<PY\nprint('$HOME')\nPY"},
            profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        )
    quoted_heredoc = "python - <<'PY'\nprint('$HOME')\nPY"
    canonical_hwe_action_json(
        "shell", {"command": quoted_heredoc}, profile_id=HWE_COLLECTION_PROFILE_V2_ID
    )
    shlex_incompatible_heredoc = "cat <<'EOF'\nit's valid heredoc data\nEOF"
    canonical_hwe_action_json(
        "shell",
        {"command": shlex_incompatible_heredoc},
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    multiline_quoted_script = "awk '\nBEGIN { print \"ok\" }\n' rtl/top.sv"
    envelope = json.loads(
        canonical_hwe_action_json(
            "shell",
            {"command": multiline_quoted_script},
            profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        )
    )
    assert envelope["arguments"]["command"] == multiline_quoted_script
    for local_status_script in (
        'false; rc=$?; test "$rc" -eq 1',
        'false; code=$?; test "${code}" -eq 1',
    ):
        envelope = json.loads(
            canonical_hwe_action_json(
                "shell",
                {"command": local_status_script},
                profile_id=HWE_COLLECTION_PROFILE_V2_ID,
            )
        )
        assert envelope["arguments"]["command"] == local_status_script
    for command in (
        'rc=1; echo "$rc"',
        "PATH=$?; command -v make",
        'echo "$HOME"; rc=$?; test "$rc" -eq 0',
    ):
        with pytest.raises(ValueError):
            canonical_hwe_action_json(
                "shell", {"command": command}, profile_id=HWE_COLLECTION_PROFILE_V2_ID
            )
    with pytest.raises(ValueError):
        canonical_hwe_action_json("shell", {"command": 'false; rc=$?; test "$rc" -eq 1'})
    with pytest.raises(ValueError, match="environment assignment"):
        canonical_hwe_action_json("shell", {"command": python_heredoc})
    with pytest.raises(ValueError, match="relative"):
        canonical_hwe_action_json(
            "read_file",
            {"path": "/etc/os-release"},
            profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        )


def test_hwe_structural_views_cover_systemverilog_and_chisel_scala() -> None:
    sv = ["// x", "module top;", "logic ready;", "endmodule", "// y"]
    scala = [
        "package core",
        "class Top extends Module {",
        "  val io = IO(new Bundle {})",
        "  when (io.valid) { io.ready := true.B }",
        "}",
    ]
    assert any("module top" in line for _, line in structural_view(sv, "rtl/top.sv"))
    assert any("class Top" in line for _, line in structural_view(scala, "src/Top.scala"))
    assert any("when" in line for _, line in structural_view(scala, "src/Top.scala"))


def test_hwe_compaction_uses_explicit_token_bounded_markers_and_diagnostics() -> None:
    compactor = HweObservationCompactor(CharacterCounter())
    shell = "\n".join(["progress"] * 9000 + ["Assertion failed expected=1 actual=0 seed=42"])
    compact = compactor.compact("shell", shell, stderr="Traceback: compile error")
    assert compact.compact_tokens <= 8192
    assert (
        compact.raw_sha256
        == hashlib.sha256(f"{shell}\n[stderr]\nTraceback: compile error".encode()).hexdigest()
    )
    assert "raw_sha256=" in compact.text
    assert "compact_tokens=" in compact.text
    assert "Assertion failed" in compact.text
    assert "Traceback" in compact.text

    listing = "\n".join(["rtl/top.sv", "vendor/ip/a.sv", *[f"rtl/f{i}.sv" for i in range(300)]])
    bounded = compactor.compact("list", listing)
    assert "vendor/ip/a.sv" not in bounded.text
    assert bounded.metadata["max_depth"] == 2
    assert bounded.omitted


def test_hwe_v2_observation_headers_and_middle_omissions_are_bounded() -> None:
    compactor = HweObservationCompactor(CharacterCounter(), profile_id=HWE_COLLECTION_PROFILE_V2_ID)
    output = "\n".join(["../repository", *[f"../repository/f{index}.sv" for index in range(400)]])
    compact = compactor.compact(
        "list",
        output,
        command="find .. -maxdepth 2 -print | sort",
        cwd=".",
        exit_code=0,
        duration_ms=17,
    )
    assert compact.rule_id == "hwe_repository_observation_v2/list_v2"
    assert compact.compact_tokens <= 2_000
    assert compact.text.startswith("[verigym-hwe result ")
    assert "find .. -maxdepth 2" in compact.text
    assert "'exit_code': 0" in compact.text
    assert "raw_sha256=" in compact.text
    assert compact.metadata["raw_line_count"] == 401
    assert compact.metadata["raw_stdout_bytes"] == len(output.encode())


def test_hwe_private_raw_artifact_is_frozen_and_secret_scanned(tmp_path: Path) -> None:
    writer = HweRawArtifactWriter(tmp_path)
    writer.append({"stdout": "public diagnostic"}, command_raw_bytes=17)
    manifest = writer.finalize()
    assert manifest["mode"] == "0400"
    assert (tmp_path / "private-audit" / "raw-events.ndjson").stat().st_mode & 0o777 == 0o400
    assert manifest["public_manifest_included"] is False

    rejected = HweRawArtifactWriter(tmp_path / "second")
    with pytest.raises(ValueError, match="secret scan"):
        rejected.append({"stdout": "authorization=abcdefghijklmnop"})

    encoded = HweRawArtifactWriter(tmp_path / "encoded")
    secret = "authorization=abcdefghijklmnop"
    with pytest.raises(ValueError, match="secret scan"):
        encoded.append(
            {"chunk": base64.b64encode(secret.encode()).decode()},
            secret_scan_text=secret,
        )


def test_hwe_private_raw_artifact_can_freeze_an_empty_failed_attempt(tmp_path: Path) -> None:
    writer = HweRawArtifactWriter(tmp_path)
    manifest = writer.finalize()
    assert manifest["records"] == 0
    assert manifest["bytes"] == 0
    assert manifest["sha256"] == hashlib.sha256(b"").hexdigest()
    assert (tmp_path / "private-audit" / "raw-events.ndjson").stat().st_mode & 0o777 == 0o400


def test_exec_protocol_compacts_file_uri_read_and_rejects_unknown(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = HweRawArtifactWriter(tmp_path / "run")
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=writer,
    )
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "fs/readFile",
        "params": {
            "path": "file:///workspace/repository/top.sv",
            "sandbox": {"untrusted": True},
        },
    }
    forwarded = json.loads(collector.client_message(json.dumps(request).encode()))
    assert forwarded["params"]["sandbox"] is None
    response = {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"dataBase64": base64.b64encode(b"module top; endmodule\n").decode()},
    }
    transformed = collector.server_message(json.dumps(response).encode())
    assert isinstance(transformed, bytes)
    compact = json.loads(transformed)
    assert compact["result"]["verigymHweObservation"]["compactTokens"] > 0
    records = collector.records()
    assert records[0].action == "read_file"
    assert records[0].arguments == {"path": "top.sv"}
    assert writer.finalize()["records"] == 1

    another = HweRawArtifactWriter(tmp_path / "unknown")
    strict = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=another,
    )
    with pytest.raises(RuntimeError, match="unknown_output_bearing"):
        strict.client_message(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "fs/newRead", "params": {}}).encode()
        )


def test_exec_protocol_maps_exact_host_workspace_uri_to_logical_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "fs/getMetadata",
        "params": {"path": (workspace / ".git").as_uri(), "sandbox": {"untrusted": True}},
    }
    forwarded = json.loads(collector.client_message(json.dumps(request).encode()))
    assert forwarded["params"]["path"] == "file:///workspace/repository/.git"
    assert forwarded["params"]["sandbox"] is None
    collector.server_message(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"kind": "directory"}}).encode()
    )
    assert collector.records()[0].arguments == {"path": ".git"}

    parent_probe = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "fs/getMetadata",
        "params": {"path": (workspace.parent / ".git").as_uri()},
    }
    forwarded_probe = json.loads(collector.client_message(json.dumps(parent_probe).encode()))
    assert forwarded_probe["params"]["path"] == (
        "file:///workspace/repository/.verigym-hwe-nonexistent-control-plane-probe"
    )
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "error": {"code": -32000, "message": "not found"},
            }
        ).encode()
    )
    assert collector.records()[1].arguments == {
        "path": ".verigym-hwe-nonexistent-control-plane-probe",
        "control_plane_probe": "git_ancestor",
    }

    skills_probe = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "fs/getMetadata",
        "params": {"path": (workspace.parent / ".agents" / "skills").as_uri()},
    }
    forwarded_skills = json.loads(collector.client_message(json.dumps(skills_probe).encode()))
    assert forwarded_skills["params"]["path"] == (
        "file:///workspace/repository/.verigym-hwe-nonexistent-control-plane-probe"
    )
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "error": {"code": -32000, "message": "not found"},
            }
        ).encode()
    )
    assert collector.records()[2].arguments["control_plane_probe"] == ("agents_skills_ancestor")

    logical_parent_probe = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "fs/getMetadata",
        "params": {"path": "file:///workspace/.git"},
    }
    forwarded_logical_parent = json.loads(
        collector.client_message(json.dumps(logical_parent_probe).encode())
    )
    assert forwarded_logical_parent["params"]["path"] == (
        "file:///workspace/repository/.verigym-hwe-nonexistent-control-plane-probe"
    )
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "error": {"code": -32000, "message": "not found"},
            }
        ).encode()
    )
    assert collector.records()[3].arguments["control_plane_probe"] == "git_ancestor"

    escaped = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "escaped"),
    )
    with pytest.raises(RuntimeError, match="filesystem_path_outside_workspace"):
        escaped.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "fs/getMetadata",
                    "params": {"path": (workspace.parent / "sibling" / ".git").as_uri()},
                }
            ).encode()
        )


def test_exec_protocol_v2_masks_external_read_only_probes_without_exposing_content(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(
            CharacterCounter(), profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        raw_writer=HweRawArtifactWriter(
            tmp_path / "metadata", profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    forwarded = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "fs/getMetadata",
                    "params": {"path": "file:///tmp/verigym-codex-home/skills"},
                }
            ).encode()
        )
    )
    assert forwarded["params"]["path"] == (
        "file:///workspace/repository/.verigym-hwe-nonexistent-control-plane-probe"
    )
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "not found"},
            }
        ).encode()
    )
    assert collector.records()[0].arguments["control_plane_probe"] == (
        "container_external_metadata_mask_v2"
    )

    direct_read = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(
            CharacterCounter(), profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        raw_writer=HweRawArtifactWriter(tmp_path / "read", profile_id=HWE_COLLECTION_PROFILE_V2_ID),
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    forwarded_read = json.loads(
        direct_read.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "fs/readFile",
                    "params": {"path": "file:///etc/os-release"},
                }
            ).encode()
        )
    )
    assert forwarded_read["params"]["path"] == (
        "file:///workspace/repository/.verigym-hwe-nonexistent-control-plane-probe"
    )
    direct_read.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "error": {"code": -32000, "message": "not found"},
            }
        ).encode()
    )
    read_record = direct_read.records()[0]
    assert read_record.action is None
    assert read_record.arguments == {
        "path": ".verigym-hwe-nonexistent-control-plane-probe",
        "control_plane_probe": "container_external_read_mask_v2",
    }

    legacy_read = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "legacy-read"),
    )
    with pytest.raises(RuntimeError, match="filesystem_path_outside_workspace"):
        legacy_read.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "fs/readFile",
                    "params": {"path": "file:///etc/os-release"},
                }
            ).encode()
        )
    legacy_failure = json.loads(
        (tmp_path / "legacy-read/private-audit/raw-events.ndjson").read_text().splitlines()[0]
    )
    assert legacy_failure["request_method"] == "fs/readFile"

    external_mutation = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(
            CharacterCounter(), profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        raw_writer=HweRawArtifactWriter(
            tmp_path / "external-mutation", profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    with pytest.raises(RuntimeError, match="filesystem_path_outside_workspace"):
        external_mutation.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "fs/writeFile",
                    "params": {
                        "path": "file:///tmp/not-a-candidate",
                        "dataBase64": base64.b64encode(b"forbidden").decode(),
                    },
                }
            ).encode()
        )


@pytest.mark.parametrize(
    ("method", "extra_params"),
    [
        ("fs/readDirectory", {}),
        ("fs/walk", {"options": {"maxDepth": 99}}),
        ("fs/open", {"handleId": "external-handle"}),
        ("fs/canonicalize", {}),
    ],
)
def test_exec_protocol_v2_masks_every_external_read_only_filesystem_method(
    tmp_path: Path,
    method: str,
    extra_params: dict[str, object],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(
            CharacterCounter(), profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        raw_writer=HweRawArtifactWriter(tmp_path / "run", profile_id=HWE_COLLECTION_PROFILE_V2_ID),
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {"path": "file:///tmp/verigym-control-plane", **extra_params},
    }
    forwarded = json.loads(collector.client_message(json.dumps(request).encode()))
    assert forwarded["params"]["path"] == (
        "file:///workspace/repository/.verigym-hwe-nonexistent-control-plane-probe"
    )
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "not found"},
            }
        ).encode()
    )
    record = collector.records()[0]
    assert record.action is None
    assert record.arguments["control_plane_probe"] == "container_external_read_mask_v2"


def test_exec_protocol_bounds_scoped_walk_without_changing_list_action(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "fs/walk",
        "params": {
            "path": "file:///workspace/repository/rtl",
            "options": {
                "maxDepth": 64,
                "maxDirectories": 10_000,
                "maxEntries": 50_000,
                "followDirectorySymlinks": True,
            },
        },
    }
    forwarded = json.loads(collector.client_message(json.dumps(request).encode()))
    assert forwarded["params"]["options"] == {
        "maxDepth": 2,
        "maxDirectories": 200,
        "maxEntries": 200,
        "followDirectorySymlinks": False,
        "pruneHiddenDirectories": True,
    }
    transformed = collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "entries": [
                        {
                            "path": f"file:///workspace/repository/rtl/f{index}.sv",
                            "kind": "file",
                        }
                        for index in range(250)
                    ],
                    "errors": [],
                    "truncated": False,
                },
            }
        ).encode()
    )
    assert isinstance(transformed, bytes)
    visible = json.loads(transformed)
    assert len(visible["result"]["entries"]) <= 200
    assert visible["result"]["truncated"] is True
    record = collector.records()[0]
    assert record.action == "list_files"
    assert record.compact_text is not None
    assert "rtl/f0.sv" in record.compact_text
    assert record.observation_omitted is True


def test_exec_protocol_waits_for_a_delayed_response_and_bounds_unresolved_details(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    collector.client_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "request-secret",
                "method": "environment/status",
                "params": {},
            }
        ).encode()
    )

    def complete() -> None:
        time.sleep(0.05)
        collector.server_message(
            json.dumps({"jsonrpc": "2.0", "id": "request-secret", "result": {}}).encode()
        )

    thread = threading.Thread(target=complete)
    thread.start()
    assert collector.wait_for_settled(timeout_s=1)[0].method == "environment/status"
    thread.join()

    unresolved = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "unresolved"),
    )
    unresolved.client_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "do-not-report",
                "method": "environment/status",
                "params": {},
            }
        ).encode()
    )
    with pytest.raises(RuntimeError, match=r"environment/status:1") as captured:
        unresolved.wait_for_settled(timeout_s=0)
    assert "do-not-report" not in str(captured.value)


def test_exec_protocol_accepts_codex_environment_info_null_params(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    forwarded = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "environment/info",
                    "params": None,
                }
            ).encode()
        )
    )
    assert forwarded["params"] == {}
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"cwd": "file:///workspace/repository"},
            }
        ).encode()
    )
    assert collector.records()[0].method == "environment/info"


def test_exec_protocol_rejects_app_server_initialize_shape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    with pytest.raises(RuntimeError, match="initialize_params_invalid"):
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "app-server", "version": "0.147.0"},
                        "capabilities": {"experimentalApi": True},
                    },
                }
            ).encode()
        )


def test_exec_protocol_correlates_bounded_process_start_stream_and_exit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = HweRawArtifactWriter(tmp_path / "run")
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=writer,
    )
    forwarded = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 15,
                    "method": "process/start",
                    "params": {
                        "argv": ["/usr/bin/bash", "-lc", "rg signal rtl"],
                        "cwd": "file:///workspace/repository",
                        "processId": "process-1",
                        "env": {"UNTRUSTED": "removed"},
                        "envPolicy": {"inherit": "all"},
                        "pipeStdin": True,
                        "tty": True,
                        "arg0": "untrusted-wrapper",
                    },
                }
            ).encode()
        )
    )
    params = forwarded["params"]
    assert params["env"] == {}
    assert params["envPolicy"]["inherit"] == "core"
    assert params["pipeStdin"] is False
    assert params["tty"] is False
    assert params["arg0"] is None
    assert params["sandbox"] is None
    assert params["networkProxy"] is None
    collector.server_message(
        json.dumps({"jsonrpc": "2.0", "id": 15, "result": {"processId": "process-1"}}).encode()
    )
    with pytest.raises(RuntimeError, match=r"process/start\(active\):1"):
        collector.records()
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/output",
                    "params": {
                        "processId": "process-1",
                        "seq": 1,
                        "stream": "stdout",
                        "chunk": "cnRsL3RvcC5zdjoxOnNpZ25hbAo=",
                    },
                }
            ).encode()
        )
        is None
    )
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/exited",
                    "params": {
                        "processId": "process-1",
                        "seq": 2,
                        "exitCode": 0,
                        "sandboxDenied": False,
                    },
                }
            ).encode()
        )
        == ()
    )
    frames = collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/closed",
                "params": {"processId": "process-1", "seq": 3},
            }
        ).encode()
    )
    assert isinstance(frames, tuple)
    compact = json.loads(frames[0])
    assert compact["method"] == "process/output"
    assert compact["params"]["chunk"] == "cnRsL3RvcC5zdjoxOnNpZ25hbA=="
    records = collector.records()
    assert len(records) == 1
    assert records[0].method == "process/start"
    assert records[0].action == "shell"
    assert records[0].arguments == {"command": "rg signal rtl"}
    assert records[0].exit_code == 0
    assert records[0].completed is True
    events, _messages = normalize_codex_hwe_events(
        protocol_records=[records[0].__dict__],
        app_server_jsonl="",
        terminal_success=True,
    )
    assert events[0].action == "shell"
    assert events[0].event_mapping == "completed process/start->shell"
    late_signal = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 16,
                    "method": "process/signal",
                    "params": {"processId": "process-1", "signal": "interrupt"},
                }
            ).encode()
        )
    )
    assert late_signal["method"] == "process/signal"
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 16,
                "error": {"code": -32000, "message": "process already closed"},
            }
        ).encode()
    )
    signal_record = collector.records()[-1]
    assert signal_record.method == "process/signal"
    assert signal_record.arguments == {
        "process_id": "process-1",
        "signal": "interrupt",
        "lifecycle_state": "closed",
    }
    late_control = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 17,
                    "method": "process/terminate",
                    "params": {"processId": "process-1"},
                }
            ).encode()
        )
    )
    assert late_control["method"] == "process/terminate"
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 17,
                "error": {"code": -32000, "message": "process already closed"},
            }
        ).encode()
    )
    assert collector.records()[-1].method == "process/terminate"
    late_write = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 18,
                    "method": "process/write",
                    "params": {"processId": "process-1", "chunk": ""},
                }
            ).encode()
        )
    )
    assert late_write["method"] == "process/write"
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 18,
                "error": {"code": -32000, "message": "process already closed"},
            }
        ).encode()
    )
    assert collector.records()[-1].arguments == {
        "process_id": "process-1",
        "lifecycle_state": "closed",
    }
    assert writer.finalize()["records"] == 7


def test_exec_protocol_v2_normalizes_only_direct_workspace_parent_process_cwd(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = HweRawArtifactWriter(tmp_path / "v2", profile_id=HWE_COLLECTION_PROFILE_V2_ID)
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(
            CharacterCounter(), profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        raw_writer=writer,
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    forwarded = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "process/start",
                    "params": {
                        "argv": ["/bin/bash", "-lc", "find .. -maxdepth 2 -type f"],
                        "cwd": "file:///workspace",
                        "processId": "parent-cwd",
                    },
                }
            ).encode()
        )
    )
    assert forwarded["params"]["cwd"] == "file:///workspace/repository"
    assert collector.completed_records() == ()
    raw_record = json.loads(
        (tmp_path / "v2/private-audit/raw-events.ndjson").read_text().splitlines()[0]
    )
    assert raw_record["rule_id"] == "direct_workspace_parent_to_repository_root_v1"
    assert "original_cwd" not in raw_record

    unrelated = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(
            CharacterCounter(), profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        raw_writer=HweRawArtifactWriter(
            tmp_path / "unrelated", profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    with pytest.raises(RuntimeError, match="filesystem_path_outside_workspace"):
        unrelated.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "process/start",
                    "params": {
                        "argv": ["/bin/bash", "-lc", "pwd"],
                        "cwd": "file:///etc",
                        "processId": "external-cwd",
                    },
                }
            ).encode()
        )

    legacy = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "legacy"),
    )
    with pytest.raises(RuntimeError, match="filesystem_path_outside_workspace"):
        legacy.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "process/start",
                    "params": {
                        "argv": ["/bin/bash", "-lc", "pwd"],
                        "cwd": "file:///workspace",
                        "processId": "legacy-parent-cwd",
                    },
                }
            ).encode()
        )


def test_exec_protocol_buffers_stream_events_that_race_ahead_of_start_response(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = HweRawArtifactWriter(tmp_path / "run")
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=writer,
    )
    collector.client_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "process/start",
                "params": {
                    "argv": ["/bin/bash", "-lc", "printf ready"],
                    "cwd": "file:///workspace/repository",
                    "processId": "racing-process",
                },
            }
        ).encode()
    )
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/output",
                    "params": {
                        "processId": "racing-process",
                        "seq": 1,
                        "stream": "stdout",
                        "chunk": base64.b64encode(b"ready").decode(),
                    },
                }
            ).encode()
        )
        is None
    )
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/exited",
                    "params": {"processId": "racing-process", "seq": 2, "exitCode": 0},
                }
            ).encode()
        )
        == ()
    )
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/closed",
                    "params": {"processId": "racing-process", "seq": 3},
                }
            ).encode()
        )
        is None
    )
    replayed = collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"processId": "racing-process"},
            }
        ).encode()
    )
    assert isinstance(replayed, tuple)
    assert len(replayed) == 4
    assert json.loads(replayed[0])["id"] == 1
    assert json.loads(replayed[1])["method"] == "process/output"
    assert json.loads(replayed[2])["method"] == "process/exited"
    assert json.loads(replayed[3])["method"] == "process/closed"
    record = collector.records()[0]
    assert record.action == "shell"
    assert record.exit_code == 0
    assert record.raw_stdout_bytes == 5
    assert writer.finalize()["records"] == 4


def test_exec_protocol_orders_output_that_arrives_after_exit_by_sequence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    collector.client_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "process/start",
                "params": {
                    "argv": ["/bin/bash", "-lc", "printf late"],
                    "cwd": "file:///workspace/repository",
                    "processId": "late-output",
                },
            }
        ).encode()
    )
    collector.server_message(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"processId": "late-output"}}).encode()
    )
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/exited",
                    "params": {"processId": "late-output", "seq": 2, "exitCode": 0},
                }
            ).encode()
        )
        == ()
    )
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/output",
                    "params": {
                        "processId": "late-output",
                        "seq": 1,
                        "stream": "stdout",
                        "chunk": base64.b64encode(b"late").decode(),
                    },
                }
            ).encode()
        )
        is None
    )
    frames = collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/closed",
                "params": {"processId": "late-output", "seq": 3},
            }
        ).encode()
    )
    assert isinstance(frames, tuple)
    assert collector.records()[0].raw_stdout_bytes == 4
    assert collector.records()[0].exit_code == 0


def test_exec_protocol_normalizes_only_frozen_logical_workspace_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "repository/core").mkdir(parents=True)
    writer = HweRawArtifactWriter(tmp_path / "run")
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=writer,
    )
    original = "pwd && sed -n '1,20p' /workspace/repository/repository/core/decoder.sv"
    forwarded = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "process/start",
                    "params": {
                        "argv": ["/bin/bash", "-lc", original],
                        "cwd": "file:///workspace/repository",
                        "processId": "process-1",
                    },
                }
            ).encode()
        )
    )
    normalized = "pwd && sed -n '1,20p' repository/core/decoder.sv"
    assert forwarded["params"]["argv"] == ["/bin/bash", "-lc", normalized]
    collector.server_message(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"processId": "process-1"}}).encode()
    )
    raw_output = (
        "/workspace/repository\n"
        "/workspace/repository/repository/core/decoder.sv\n"
        "file:///workspace/repository/repository/core/decoder.sv\n"
    )
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/output",
                "params": {
                    "processId": "process-1",
                    "seq": 1,
                    "stream": "stdout",
                    "chunk": base64.b64encode(raw_output.encode()).decode(),
                },
            }
        ).encode()
    )
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/exited",
                    "params": {
                        "processId": "process-1",
                        "seq": 2,
                        "exitCode": 0,
                        "sandboxDenied": False,
                    },
                }
            ).encode()
        )
        == ()
    )
    frames = collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/closed",
                "params": {"processId": "process-1", "seq": 3},
            }
        ).encode()
    )
    compact = base64.b64decode(json.loads(frames[0])["params"]["chunk"]).decode()
    assert compact == ".\nrepository/core/decoder.sv\nrepository/core/decoder.sv"
    assert collector.records()[0].arguments == {"command": normalized}
    writer.finalize()
    audit = (tmp_path / "run/private-audit/raw-events.ndjson").read_text(encoding="utf-8")
    assert "logical_workspace_root_to_relative_v1" in audit
    assert original in audit
    assert normalized in audit

    for request_id, command in enumerate(
        ("cat /etc/passwd", "cat /workspace/repository-other/secret"), start=2
    ):
        rejected = HweExecProtocolCollector(
            workspace_root=workspace,
            compactor=HweObservationCompactor(CharacterCounter()),
            raw_writer=HweRawArtifactWriter(tmp_path / f"rejected-{request_id}"),
        )
        with pytest.raises(RuntimeError, match="shell_command_policy_violation:absolute_path"):
            rejected.client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "process/start",
                        "params": {
                            "argv": ["/bin/bash", "-lc", command],
                            "cwd": "file:///workspace/repository",
                            "processId": f"process-{request_id}",
                        },
                    }
                ).encode()
            )


def test_exec_protocol_v2_preserves_container_native_parent_and_absolute_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = HweRawArtifactWriter(tmp_path / "run", profile_id=HWE_COLLECTION_PROFILE_V2_ID)
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(
            CharacterCounter(), profile_id=HWE_COLLECTION_PROFILE_V2_ID
        ),
        raw_writer=writer,
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    command = "find .. -maxdepth 2 -print && sed -n '1p' /etc/os-release"
    forwarded = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "process/start",
                    "params": {
                        "argv": ["/bin/bash", "-lc", command],
                        "cwd": "file:///workspace/repository",
                        "processId": "process-v2",
                    },
                }
            ).encode()
        )
    )
    assert forwarded["params"]["argv"] == ["/bin/bash", "-lc", command]
    assert forwarded["params"]["env"] == {"VERILATOR_ROOT": "/tools/verilator"}
    collector.server_message(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"processId": "process-v2"}}).encode()
    )
    raw_output = "../repository\n/workspace/repository/TASK.md\n"
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/output",
                "params": {
                    "processId": "process-v2",
                    "seq": 1,
                    "stream": "stdout",
                    "chunk": base64.b64encode(raw_output.encode()).decode(),
                },
            }
        ).encode()
    )
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/exited",
                    "params": {"processId": "process-v2", "seq": 2, "exitCode": 0},
                }
            ).encode()
        )
        == ()
    )
    frames = collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/closed",
                "params": {"processId": "process-v2", "seq": 3},
            }
        ).encode()
    )
    assert isinstance(frames, tuple)
    compact = base64.b64decode(json.loads(frames[0])["params"]["chunk"]).decode()
    assert compact.startswith("[verigym-hwe result ")
    assert command in compact
    assert "/workspace/repository/TASK.md" in compact
    record = collector.records()[0]
    assert record.arguments == {"command": command}
    assert record.raw_stdout_bytes == len(raw_output.encode())
    assert record.raw_stderr_bytes == 0
    assert record.duration_ms is not None
    events, _messages = normalize_codex_hwe_events(
        protocol_records=[record.__dict__],
        app_server_jsonl="",
        terminal_success=True,
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    assert events[0].arguments == {"command": command}
    assert events[0].exit_code == 0
    assert writer.finalize()["observation_policy_id"] == "hwe_repository_observation_v2"


def test_exec_protocol_unwraps_bounded_bash_c_capability_probe(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    forwarded = json.loads(
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "process/start",
                    "params": {
                        "argv": ["/usr/bin/bash", "-c", "echo hi"],
                        "cwd": "file:///workspace/repository",
                        "processId": "process-1",
                    },
                }
            ).encode()
        )
    )
    assert forwarded["params"]["argv"] == ["/usr/bin/bash", "-c", "echo hi"]
    assert collector.completed_records() == ()


def test_exec_protocol_rejects_concurrent_process_start_before_epoch_overlap(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    collector.client_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "process/start",
                "params": {
                    "argv": ["/bin/bash", "-lc", "rg first rtl"],
                    "cwd": "file:///workspace/repository",
                    "processId": "first-process",
                },
            }
        ).encode()
    )
    collector.server_message(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"processId": "first-process"}}).encode()
    )
    with pytest.raises(RuntimeError, match="concurrent_process_start_forbidden"):
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "process/start",
                    "params": {
                        "argv": ["/bin/bash", "-lc", "rg second rtl"],
                        "cwd": "file:///workspace/repository",
                        "processId": "second-process",
                    },
                }
            ).encode()
        )


def test_exec_protocol_correlates_active_interrupt_and_rejects_unsafe_control(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    active = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "active"),
    )
    active.client_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "process/start",
                "params": {
                    "argv": ["/bin/bash", "-lc", "rg signal rtl"],
                    "cwd": "file:///workspace/repository",
                    "processId": "active-process",
                },
            }
        ).encode()
    )
    active.server_message(
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"processId": "active-process"}}).encode()
    )
    forwarded = json.loads(
        active.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "process/signal",
                    "params": {"processId": "active-process", "signal": "interrupt"},
                }
            ).encode()
        )
    )
    assert forwarded["method"] == "process/signal"
    active.server_message(json.dumps({"jsonrpc": "2.0", "id": 2, "result": {}}).encode())
    active.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/exited",
                "params": {
                    "processId": "active-process",
                    "seq": 1,
                    "exitCode": 130,
                    "sandboxDenied": False,
                },
            }
        ).encode()
    )
    active.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/closed",
                "params": {"processId": "active-process", "seq": 2},
            }
        ).encode()
    )
    shell_record = next(record for record in active.records() if record.action == "shell")
    assert shell_record.interrupted_by_agent is True
    assert "[verigym-hwe process interrupted by agent]" in (shell_record.compact_text or "")
    events, _messages = normalize_codex_hwe_events(
        protocol_records=[record.__dict__ for record in active.records()],
        app_server_jsonl="",
        terminal_success=True,
    )
    assert events[0].event_mapping == ("completed interrupted process/start+process/signal->shell")

    active_write = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "active-write"),
    )
    active_write.client_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "process/start",
                "params": {
                    "argv": ["/bin/bash", "-lc", "rg signal rtl"],
                    "cwd": "file:///workspace/repository",
                    "processId": "active-write-process",
                },
            }
        ).encode()
    )
    active_write.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"processId": "active-write-process"},
            }
        ).encode()
    )
    with pytest.raises(RuntimeError, match="interactive_process_control_forbidden:process/write"):
        active_write.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "process/write",
                    "params": {"processId": "active-write-process", "chunk": "data"},
                }
            ).encode()
        )

    exited = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "exited"),
    )
    exited.client_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "process/start",
                "params": {
                    "argv": ["/bin/bash", "-lc", "rg signal rtl"],
                    "cwd": "file:///workspace/repository",
                    "processId": "exited-process",
                },
            }
        ).encode()
    )
    exited.server_message(
        json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"processId": "exited-process"}}).encode()
    )
    exited.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/exited",
                "params": {
                    "processId": "exited-process",
                    "seq": 1,
                    "exitCode": 0,
                    "sandboxDenied": False,
                },
            }
        ).encode()
    )
    with pytest.raises(RuntimeError, match="process_signal_invalid"):
        exited.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "process/signal",
                    "params": {"processId": "exited-process", "signal": "kill"},
                }
            ).encode()
        )


def test_exec_protocol_reorders_early_close_only_after_causal_exit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=HweRawArtifactWriter(tmp_path / "run"),
    )
    collector.client_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "process/start",
                "params": {
                    "argv": ["/bin/bash", "-lc", "rg close rtl"],
                    "cwd": "file:///workspace/repository",
                    "processId": "reordered-process",
                },
            }
        ).encode()
    )
    collector.server_message(
        json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"processId": "reordered-process"}}
        ).encode()
    )
    collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/output",
                "params": {
                    "processId": "reordered-process",
                    "seq": 1,
                    "stream": "stdout",
                    "chunk": base64.b64encode(b"rtl/top.sv:1:close").decode(),
                },
            }
        ).encode()
    )
    assert (
        collector.server_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "process/closed",
                    "params": {"processId": "reordered-process", "seq": 3},
                }
            ).encode()
        )
        is None
    )
    frames = collector.server_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "process/exited",
                "params": {
                    "processId": "reordered-process",
                    "seq": 2,
                    "exitCode": 0,
                    "sandboxDenied": False,
                },
            }
        ).encode()
    )
    assert isinstance(frames, tuple)
    assert [json.loads(frame)["method"] for frame in frames[-2:]] == [
        "process/exited",
        "process/closed",
    ]
    record = next(record for record in collector.records() if record.action == "shell")
    assert record.completed is True
    assert record.exit_code == 0


def test_exec_protocol_persists_specific_failure_without_raw_request_values(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = HweRawArtifactWriter(tmp_path / "run")
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=writer,
    )
    with pytest.raises(RuntimeError, match="process_control_without_known_process"):
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "private-request-id",
                    "method": "process/write",
                    "params": {
                        "processId": "private-process-handle",
                        "chunk": "c2Vuc2l0aXZl",
                    },
                }
            ).encode()
        )
    manifest = writer.finalize()
    audit = (tmp_path / "run" / "private-audit" / "raw-events.ndjson").read_text(encoding="utf-8")
    assert manifest["records"] == 1
    assert "process_control_without_known_process" in audit
    assert "private-request-id" not in audit
    assert "private-process-handle" not in audit
    assert "c2Vuc2l0aXZl" not in audit


def test_exec_protocol_records_rejected_shell_only_in_private_audit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writer = HweRawArtifactWriter(tmp_path / "run")
    collector = HweExecProtocolCollector(
        workspace_root=workspace,
        compactor=HweObservationCompactor(CharacterCounter()),
        raw_writer=writer,
    )
    forbidden_command = "FOO=private-value make"
    with pytest.raises(
        RuntimeError,
        match="shell_command_policy_violation:environment_assignment",
    ):
        collector.client_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "process/start",
                    "params": {
                        "argv": ["/bin/bash", "-lc", forbidden_command],
                        "cwd": "file:///workspace/repository",
                        "processId": "process-1",
                    },
                }
            ).encode()
        )
    assert writer.finalize()["records"] == 1
    record = json.loads(
        (tmp_path / "run/private-audit/raw-events.ndjson").read_text(encoding="utf-8")
    )
    assert record["policy_subreason"] == "environment_assignment"
    assert len(record["rejected_request_sha256"]) == 64
    assert record["rejected_command"] == forbidden_command


def test_codex_0147_patch_updated_schema_preserves_diffs_and_paths() -> None:
    diff = "--- a/rtl/top.sv\n+++ b/rtl/top.sv\n@@ -1 +1 @@\n-old\n+new\n"
    event = _normalize_app_server_notification(
        "item/fileChange/patchUpdated",
        {
            "threadId": "thread",
            "turnId": "turn",
            "itemId": "item",
            "changes": [
                {
                    "path": "/workspace/repository/rtl/top.sv",
                    "diff": diff,
                    "kind": {"type": "update", "move_path": None},
                }
            ],
        },
    )
    assert event is not None
    assert event["patch"] == diff
    assert event["paths"] == ["rtl/top.sv"]


def test_hwe_normalization_does_not_invent_missing_patch_and_records_finish() -> None:
    mutation = {
        "completed": True,
        "method": "fs/writeFile",
        "action": None,
        "arguments": {"path": "rtl/top.sv"},
        "workspace_epoch_before": 0,
        "workspace_epoch_after": 1,
        "changed_paths": ["rtl/top.sv"],
        "raw_bytes": 10,
        "compact_tokens": 0,
    }
    with pytest.raises(HweCausalValidationError, match="cannot be fabricated") as captured:
        normalize_codex_hwe_events(
            protocol_records=[mutation], app_server_jsonl="", terminal_success=True
        )
    assert captured.value.reason == "filesystem_mutation_without_patch_update"
    patch = "--- a/rtl/top.sv\n+++ b/rtl/top.sv\n@@ -1 +1 @@\n-old\n+new\n"
    events, messages = normalize_codex_hwe_events(
        protocol_records=[mutation],
        app_server_jsonl=json.dumps({"type": "file_change.patch_updated", "patch": patch}),
        terminal_success=True,
    )
    assert [event.action for event in events] == ["apply_patch", "finish"]
    assert events[0].changed_paths == ("rtl/top.sv",)
    assert messages[-1]["role"] == "assistant"


def test_hwe_transcript_formats_metrics_and_causal_manifest_are_independent() -> None:
    counter = CharacterCounter()
    list_arguments = json.loads(canonical_hwe_action_json("list_files", {}))["arguments"]
    finish_arguments = {"summary": "done"}
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        _assistant_call("c0", "list_files", list_arguments),
        {"role": "tool", "content": "rtl/", "tool_call_id": "c0", "name": "list_files"},
        _assistant_call("c1", "finish", finish_arguments),
        {"role": "tool", "content": "finished", "tool_call_id": "c1", "name": "finish"},
        {"role": "assistant", "content": "submitted"},
    ]
    events = [
        HweNormalizedEvent(
            sequence=0,
            action="list_files",
            arguments=list_arguments,
            workspace_epoch_before=0,
            workspace_epoch_after=0,
            raw_observation_sha256="1" * 64,
            raw_observation_bytes=100,
            compact_observation_sha256="2" * 64,
            compact_observation_tokens=4,
            event_mapping="fs/readDirectory->list_files",
        ),
        HweNormalizedEvent(
            sequence=1,
            action="finish",
            arguments=finish_arguments,
            workspace_epoch_before=0,
            workspace_epoch_after=0,
            event_mapping="turn/completed->finish",
        ),
    ]
    transcript = build_hwe_teacher_transcript(
        task_id="openhwgroup/cva6:pr-2032",
        model_id="gpt-5.4",
        client_version="codex-cli 0.147.0",
        client_sha256="a" * 64,
        agent_image_lock_hash="b" * 64,
        messages=messages,
        normalized_events=events,
        counter=counter,
        api_input_tokens=1000,
        api_output_tokens=100,
        raw_layer_hash="c" * 64,
    )
    assert transcript["format_id"] == "verigym_hwe_teacher_multiturn_transcript_v2"
    assert transcript["primary_eligible"] is True
    assert transcript["metrics"]["decision_steps"] == 1
    assert transcript["compaction_manifest"]["causal_validation"] == "passed"
    assert validate_hwe_teacher_transcript(transcript) == transcript


def test_hwe_v2_transcript_records_container_scope_limits_and_step_outcomes() -> None:
    counter = CharacterCounter()
    shell_arguments = {"command": "find /opt -maxdepth 1 -print"}
    finish_arguments = {"summary": "done"}
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        _assistant_call("c0", "shell", shell_arguments),
        {"role": "tool", "content": "/opt", "tool_call_id": "c0", "name": "shell"},
        _assistant_call("c1", "finish", finish_arguments),
        {"role": "tool", "content": "finished", "tool_call_id": "c1", "name": "finish"},
        {"role": "assistant", "content": "submitted"},
    ]
    events = [
        HweNormalizedEvent(
            0,
            "shell",
            shell_arguments,
            0,
            0,
            exit_code=0,
            duration_ms=12,
            raw_stdout_bytes=5,
            raw_stderr_bytes=0,
            raw_stdout_sha256="1" * 64,
            raw_stderr_sha256=hashlib.sha256(b"").hexdigest(),
            event_mapping="completed process/start->shell",
        ),
        HweNormalizedEvent(1, "finish", finish_arguments, 0, 0, event_mapping="finish"),
    ]
    transcript = build_hwe_teacher_transcript(
        task_id="openhwgroup/cva6:pr-2032",
        model_id="gpt-5.4",
        client_version="codex-cli 0.147.0",
        client_sha256="a" * 64,
        agent_image_lock_hash="b" * 64,
        messages=messages,
        normalized_events=events,
        counter=counter,
        api_input_tokens=100,
        api_output_tokens=10,
        raw_layer_hash="c" * 64,
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    assert transcript["format_id"] == "verigym_hwe_teacher_multiturn_transcript_v3"
    assert transcript["container_read_scope"] == "isolated_agent_container"
    assert transcript["candidate_write_scope"] == "/workspace/repository"
    assert transcript["exit_reason"] == "agent_finish"
    assert transcript["compaction_manifest"]["format_id"] == ("verigym_hwe_compaction_manifest_v2")
    assert transcript["compaction_manifest"]["step_outcomes"][0]["exit_code"] == 0
    assert transcript["metrics"]["command_duration_ms"] == 12
    assert validate_hwe_teacher_transcript(transcript) == transcript


def test_hwe_history_masking_preserves_actions_and_pins_current_epoch_diagnostics() -> None:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]
    outcomes: list[dict[str, object]] = []
    for sequence in range(20):
        if sequence == 2:
            command = "make compile-failing"
            exit_code = 1
        elif sequence == 3:
            command = "make compile-passing"
            exit_code = 0
        elif sequence == 4:
            command = "inspect"
            exit_code = None
            action = "inspect_diff"
            arguments: dict[str, object] = {}
        else:
            command = f"printf observation-{sequence}"
            exit_code = 0
        if sequence != 4:
            action = "shell"
            arguments = {"command": command}
        messages.append(_assistant_call(f"c{sequence}", action, arguments))
        messages.append(
            {
                "role": "tool",
                "content": f"observation-{sequence}-" + "x" * 120,
                "tool_call_id": f"c{sequence}",
                "name": action,
            }
        )
        outcomes.append(
            {
                "sequence": sequence,
                "action": action,
                "exit_code": exit_code,
                "duration_ms": 1,
                "raw_stdout_bytes": 10,
                "raw_stderr_bytes": 0,
                "raw_stdout_sha256": "1" * 64,
                "raw_stderr_sha256": "2" * 64,
                "workspace_epoch_before": 0,
                "workspace_epoch_after": 0,
                "changed_paths": [],
            }
        )
    messages.append({"role": "assistant", "content": "submitted"})

    policy = HweHistoryMaskingPolicy(recent_observations=8)
    views = derive_hwe_masked_history_views(
        messages,
        step_outcomes=outcomes,
        counter=CharacterCounter(),
        policy=policy,
    )
    ledger = views[-1]["history_ledger"]
    assert ledger["policy_id"] == HWE_HISTORY_MASKING_POLICY_ID
    assert ledger["recent_observation_sequences"] == list(range(11, 19))
    assert ledger["pinned_observation_sequences"] == [2, 3, 4]
    assert ledger["masked_observation_sequences"] == [0, 1, *range(5, 11)]
    assert ledger["all_prior_actions_preserved"] is True
    assert ledger["counterfactual_next_action_validation"] == "not_run"
    masked_tools = [
        message["content"]
        for message in views[-1]["messages"]
        if message.get("role") == "tool"
        and isinstance(message.get("content"), str)
        and "masked-observation" in message["content"]
    ]
    assert len(masked_tools) == 8
    assert all("content_sha256=" in content for content in masked_tools)
    assert all("observation-0-" not in content for content in masked_tools)
    assert views[-1]["messages"][-1] == messages[40]
    assert summarize_hwe_masking_views(views)["structural_action_preservation"] == "passed"
    with pytest.raises(ValueError, match="M=8"):
        HweHistoryMaskingPolicy(recent_observations=9)  # type: ignore[arg-type]


def test_hwe_lossless_history_view_is_explicit_and_within_length() -> None:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]
    outcomes: list[dict[str, object]] = []
    for sequence in range(4):
        messages.append(_assistant_call(f"c{sequence}", "shell", {"command": "true"}))
        messages.append(
            {
                "role": "tool",
                "content": f"observation-{sequence}",
                "tool_call_id": f"c{sequence}",
                "name": "shell",
            }
        )
        outcomes.append(
            {
                "sequence": sequence,
                "action": "shell",
                "changed_paths": [],
                "workspace_epoch_before": 0,
                "workspace_epoch_after": 0,
                "exit_code": 0,
            }
        )
    messages.append({"role": "assistant", "content": "submitted"})

    view = derive_hwe_lossless_history_view(
        messages,
        step_outcomes=outcomes,
        counter=CharacterCounter(),
        target_sequence=3,
    )
    ledger = view["history_ledger"]
    assert ledger["policy_id"] == HWE_LOSSLESS_HISTORY_POLICY_ID
    assert ledger["retained_observation_sequences"] == [0, 1, 2]
    assert ledger["masked_observation_sequences"] == []
    assert view["messages"] == messages[:8] + [messages[8]]
    assert view["within_32k"] is True


def test_hwe_action_conditioned_format_accepts_long_context_source_without_relabeling_primary(
    tmp_path: Path,
) -> None:
    counter = CharacterCounter()
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]
    events: list[HweNormalizedEvent] = []
    for sequence in range(15):
        arguments = {"command": f"printf step-{sequence}"}
        messages.append(_assistant_call(f"c{sequence}", "shell", arguments))
        messages.append(
            {
                "role": "tool",
                "content": f"unique-{sequence}-" + chr(65 + sequence) * 2_200,
                "tool_call_id": f"c{sequence}",
                "name": "shell",
            }
        )
        events.append(
            HweNormalizedEvent(
                sequence,
                "shell",
                arguments,
                0,
                0,
                exit_code=0,
                duration_ms=1,
                event_mapping="completed process/start->shell",
            )
        )
    finish_arguments = {"summary": "done"}
    messages.append(_assistant_call("c15", "finish", finish_arguments))
    messages.append(
        {
            "role": "tool",
            "content": "finished",
            "tool_call_id": "c15",
            "name": "finish",
        }
    )
    messages.append({"role": "assistant", "content": "submitted"})
    events.append(HweNormalizedEvent(15, "finish", finish_arguments, 0, 0, event_mapping="finish"))
    transcript = build_hwe_teacher_transcript(
        task_id="openhwgroup/cva6:pr-2032",
        model_id="gpt-5.4",
        client_version="codex-cli 0.147.0",
        client_sha256="a" * 64,
        agent_image_lock_hash="b" * 64,
        messages=messages,
        normalized_events=events,
        counter=counter,
        api_input_tokens=100,
        api_output_tokens=10,
        raw_layer_hash="c" * 64,
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    )
    assert transcript["sft_bucket"] == "long_context_candidate"
    assert transcript["primary_eligible"] is False
    binding = {
        "sample_id": "1" * 64,
        "task_hash": "2" * 64,
        "source_hash": "3" * 64,
        "candidate_hash": "4" * 64,
        "verifier_hash": "5" * 64,
    }
    examples = materialize_hwe_action_conditioned_examples(
        transcript,
        binding=binding,
        counter=counter,
        policy=HweHistoryMaskingPolicy(recent_observations=8),
    )
    assert len(examples) == 16
    assert max(example["token_count"] for example in examples) < 32_768
    assert {example["format_id"] for example in examples} == {HWE_ACTION_CONDITIONED_SFT_FORMAT}
    assert all(example["primary_eligible"] is False for example in examples)
    assert all(example["source_primary_eligible"] is False for example in examples)
    assert all(
        example["supervised_message_indices"] == [len(example["messages"]) - 1]
        for example in examples
    )
    assert validate_hwe_action_conditioned_example(examples[-1]) == examples[-1]
    minimal_examples = materialize_hwe_action_conditioned_examples(
        transcript,
        binding=binding,
        counter=counter,
        policy=HweHistoryMaskingPolicy(
            recent_observations=1,
            max_pinned_observations=1,
        ),
    )
    assert minimal_examples[-1]["history_ledger"]["recent_observations"] == 1
    assert minimal_examples[-1]["history_ledger"]["max_pinned_observations"] == 1
    assert validate_hwe_action_conditioned_example(minimal_examples[-1]) == minimal_examples[-1]
    dataset = build_hwe_action_conditioned_dataset_manifest(examples)
    assert dataset["format_id"] == HWE_ACTION_CONDITIONED_DATASET_FORMAT
    assert dataset["trajectory_count"] == 1
    assert dataset["record_count"] == 16
    assert dataset["primary_eligible"] is False
    assert dataset["hpc_jobs_submitted"] is False
    example_schema = json.loads(
        Path("docs/schemas/hwe-action-conditioned-sft.schema.json").read_text(encoding="utf-8")
    )
    dataset_schema = json.loads(
        Path("docs/schemas/hwe-action-conditioned-sft-dataset.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(example_schema).validate(examples[-1])
    jsonschema.Draft202012Validator(dataset_schema).validate(dataset)

    tampered = json.loads(json.dumps(examples[-1]))
    tampered["history_ledger"]["counterfactual_next_action_validation"] = "passed"
    with pytest.raises(ValueError, match="identity changed"):
        validate_hwe_action_conditioned_example(tampered)

    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")
    analysis = analyze_transcripts([transcript_path], windows=[8, 10, 16])
    assert analysis["format_id"] == "verigym_hwe_observation_masking_analysis_v1"
    assert analysis["selected_window"] == 16
    assert analysis["live_rollout_masking_applied"] is False
    assert analysis["existing_primary_reclassified"] is False
    assert all(item["all_trajectories_within_32k"] for item in analysis["summary_by_window"])
    analysis_schema = json.loads(
        Path("docs/schemas/hwe-observation-masking-analysis.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(analysis_schema).validate(analysis)


def test_secondary_compaction_uses_observed_epochs_not_shell_action_names() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        _assistant_call("c0", "shell", {"command": "pwd"}),
        {"role": "tool", "content": "same", "tool_call_id": "c0", "name": "shell"},
        _assistant_call("c1", "read_file", {"path": "rtl/top.sv"}),
        {
            "role": "tool",
            "content": "same",
            "tool_call_id": "c1",
            "name": "read_file",
        },
        _assistant_call("c2", "finish", {"summary": "done"}),
        {"role": "tool", "content": "done", "tool_call_id": "c2", "name": "finish"},
        {"role": "assistant", "content": "submitted"},
    ]
    events = [
        HweNormalizedEvent(0, "shell", {"command": "pwd"}, 0, 0),
        HweNormalizedEvent(1, "read_file", {"path": "rtl/top.sv"}, 0, 0),
        HweNormalizedEvent(2, "finish", {"summary": "done"}, 0, 0),
    ]
    compacted, manifest = secondary_sft_compaction(messages, events)
    assert compacted[5]["content"].startswith("[verigym-hwe identical-observation")
    assert manifest[1]["workspace_epoch"] == 0


def test_hwe_step_budget_and_pilot_gate() -> None:
    budget = HweEpisodeBudget(decision_steps=200)
    with pytest.raises(HweLimitExceeded, match="decision_steps"):
        budget.observe("read_file")
    pool = (
        *HWE_PILOT_TASKS,
        *(f"hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-{3000 + i}" for i in range(8)),
    )
    state = HweCampaignState(pool, "unit-hwe-campaign")
    report = state.report()
    assert report["prompt_contract_id"] == HWE_CODEX_PROMPT_CONTRACT_ID
    assert report["prompt_contract_version"] == HWE_CODEX_PROMPT_CONTRACT_VERSION
    assert report["base_instruction_policy"] == HWE_CODEX_BASE_INSTRUCTION_POLICY
    statuses = ["primary_eligible", "primary_eligible", "verifier_rejected"]
    for task_id, status in zip(HWE_PILOT_TASKS, statuses, strict=True):
        state.record(
            HweCampaignAttempt(
                task_id=task_id,
                status=status,  # type: ignore[arg-type]
                infrastructure_valid=True,
                verifier_pass=status == "primary_eligible",
                normalized_success=status == "primary_eligible",
                sft_bucket="primary" if status == "primary_eligible" else None,
                run_hash=content_hash({"task": task_id}),
                rejection_reason=None if status == "primary_eligible" else "verifier_rejected",
            )
        )
    assert state.status == "production_running"
    assert state.report()["pilot_is_benchmark_score"] is False


def test_action_conditioned_campaign_has_separate_pilot_gate_and_counts() -> None:
    pool = (
        *HWE_PILOT_TASKS,
        *(f"hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-{3000 + i}" for i in range(8)),
    )
    image_locks = tuple(
        sorted((task_id, content_hash({"image_lock": task_id})) for task_id in pool)
    )
    state = HweActionConditionedCampaignState(
        pool,
        "unit-action-conditioned-campaign",
        image_locks,
    )
    statuses = [
        "action_conditioned_eligible_success",
        "verifier_rejected",
        "action_conditioned_eligible_success",
    ]
    for task_id, status in zip(HWE_PILOT_TASKS, statuses, strict=True):
        eligible = status == "action_conditioned_eligible_success"
        state.record(
            HweActionConditionedCampaignAttempt(
                task_id=task_id,
                status=status,  # type: ignore[arg-type]
                infrastructure_valid=True,
                verifier_pass=eligible,
                normalized_success=eligible,
                source_sft_bucket="long_context_candidate" if eligible else None,
                action_conditioned_eligible=eligible,
                action_record_count=64 if eligible else 0,
                max_action_record_tokens=29_968 if eligible else None,
                source_transcript_hash=content_hash({"transcript": task_id}) if eligible else None,
                action_records_hash=content_hash({"records": task_id}) if eligible else None,
                run_hash=content_hash({"run": task_id}),
                rejection_reason=None if eligible else "benchmark_verifier_rejected",
            )
        )
    report = state.report()
    assert state.status == "production_running"
    assert report["action_conditioned_eligible_success"] == 2
    assert report["action_record_count"] == 128
    assert report["history_recent_observations"] == 16
    assert report["training_eligibility"] == "experimental_action_conditioned"
    assert report["primary_eligible"] == 0
    assert report["existing_primary_reclassified"] is False
    assert report["pilot_is_benchmark_score"] is False

    rejected_task = state.next_task()
    assert rejected_task is not None
    state.record(
        HweActionConditionedCampaignAttempt(
            task_id=rejected_task,
            status="agent_policy_rejected",
            infrastructure_valid=True,
            verifier_pass=False,
            normalized_success=False,
            source_sft_bucket=None,
            action_conditioned_eligible=False,
            action_record_count=0,
            max_action_record_tokens=None,
            source_transcript_hash=None,
            action_records_hash=None,
            run_hash=content_hash({"run": rejected_task}),
            rejection_reason="hwe_protocol_shell_command_policy_violation:tokenization",
            external_model_call_count=1,
            protocol_error_subcategory=("hwe_protocol_shell_command_policy_violation:tokenization"),
        )
    )
    assert state.status == "production_running"
    assert state.report()["agent_policy_rejected"] == 1
    assert state.next_task() != rejected_task

    minimal_state = HweActionConditionedCampaignState(
        pool,
        "unit-action-conditioned-minimal-history",
        image_locks,
        history_recent_observations=1,
        history_max_pinned_observations=1,
    )
    minimal_report = minimal_state.report()
    assert minimal_report["history_recent_observations"] == 1
    assert minimal_report["history_max_pinned_observations"] == 1
    assert (
        minimal_report["history_policy_hash"]
        == HweHistoryMaskingPolicy(
            recent_observations=1,
            max_pinned_observations=1,
        ).policy_hash
    )

    failed = HweActionConditionedCampaignState(
        pool,
        "unit-action-conditioned-failed",
        image_locks,
    )
    for task_id, eligible in zip(HWE_PILOT_TASKS, (True, False, True), strict=True):
        failed.record(
            HweActionConditionedCampaignAttempt(
                task_id=task_id,
                status=(
                    "action_conditioned_eligible_success"
                    if eligible
                    else "action_conditioned_ineligible"
                ),
                infrastructure_valid=True,
                verifier_pass=True,
                normalized_success=True,
                source_sft_bucket="long_context_candidate",
                action_conditioned_eligible=eligible,
                action_record_count=1 if eligible else 0,
                max_action_record_tokens=10 if eligible else None,
                source_transcript_hash=content_hash({"transcript": task_id}),
                action_records_hash=content_hash({"records": task_id}) if eligible else None,
                run_hash=content_hash({"run": task_id}),
                rejection_reason=None if eligible else "action_conditioned_record_exceeds_32k",
            )
        )
    assert failed.status == "stopped_pilot_gate_failed"


def test_action_conditioned_status_does_not_require_full_transcript_primary_bucket() -> None:
    transcript = {"sft_bucket": "long_context_candidate"}
    assert _action_conditioned_status(True, True, transcript) == (
        "action_conditioned_eligible_success",
        None,
    )
    assert _action_conditioned_status(False, True, transcript) == (
        "verifier_rejected",
        "benchmark_verifier_rejected",
    )
    policy_reason = "hwe_protocol_shell_command_policy_violation:tokenization"
    assert _action_conditioned_status(
        False,
        True,
        None,
        model_action_rejection=policy_reason,
    ) == ("agent_policy_rejected", policy_reason)


def test_hwe_materialization_rejection_is_normalized_failure_not_infrastructure(
    tmp_path: Path,
) -> None:
    task_id = HWE_PILOT_TASKS[1]
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_hwe_materialization_rejection_v1",
        "collection_profile_id": HWE_COLLECTION_PROFILE_V2_ID,
        "task_id": task_id,
        "reason": "filesystem_mutation_without_patch_update",
        "ordinary_verifier_resolved": True,
        "terminal_event_seen": True,
        "protocol_record_count": 8,
        "raw_layer_hash": "a" * 64,
    }
    path = tmp_path / "hwe_materialization_rejection.json"
    path.write_text(json.dumps({**base, "rejection_hash": content_hash(base)}), encoding="utf-8")
    rejection = _materialization_rejection(path, task_id=task_id)
    assert rejection == "hwe_materialization_filesystem_mutation_without_patch_update"
    assert _status(True, True, None, materialization_rejection=rejection) == (
        "normalized_failure",
        rejection,
    )


def test_zero_call_startup_restart_requires_cleanup_and_unchanged_workspace(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    runtime_root = run / "artifacts/codex_cli"
    runtime_root.mkdir(parents=True)
    (runtime_root / "runtime_process.json").write_text(
        json.dumps({"cleanup_complete": True}), encoding="utf-8"
    )
    failure = SimpleNamespace(
        category="protocol_error",
        protocol_error_subcategory="exec_server_handshake_failed",
        message="local handshake failed",
        infrastructure=True,
        kind="runtime",
    )
    scorecard = SimpleNamespace(
        efficiency=SimpleNamespace(external_model_call_count=0),
        correctness=SimpleNamespace(infrastructure_error=True),
        patch=SimpleNamespace(changed_files=[]),
        failure=failure,
        status="error",
        model_dump=lambda **_kwargs: {"status": "error", "model_calls": 0},
    )
    result = SimpleNamespace(run_dir=run, scorecard=scorecard)
    assert _zero_call_startup_restart_eligible(result)
    record = _startup_restart_record(
        task_id="hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2032",
        launch_id="campaign-pr-2032-launch-1",
        launch_count=1,
        scorecard=scorecard,
    )
    _write_startup_restarts(tmp_path, [record])
    assert _load_startup_restarts(tmp_path) == [record]

    scorecard.efficiency.external_model_call_count = 1
    assert not _zero_call_startup_restart_eligible(result)
    scorecard.efficiency.external_model_call_count = 0
    scorecard.patch.changed_files = ["repository/rtl/top.sv"]
    assert not _zero_call_startup_restart_eligible(result)


def test_sampled_model_policy_rejection_is_not_campaign_infrastructure_failure() -> None:
    subcategory = "hwe_protocol_shell_command_policy_violation:tokenization"
    scorecard = SimpleNamespace(
        efficiency=SimpleNamespace(external_model_call_count=1),
        failure=SimpleNamespace(
            kind="model",
            category="protocol_error",
            protocol_error_subcategory=subcategory,
        ),
    )
    assert _model_action_rejection(scorecard) == subcategory
    scorecard.failure.protocol_error_subcategory = "hwe_protocol_unknown_output_bearing_method"
    assert _model_action_rejection(scorecard) is None
    scorecard.efficiency.external_model_call_count = 0
    scorecard.failure.protocol_error_subcategory = subcategory
    assert _model_action_rejection(scorecard) is None


def test_task_keyed_image_lock_binds_codex_and_security_scan() -> None:
    values = {
        "task_id": "openhwgroup/cva6:pr-2032",
        "task_hash": "1" * 64,
        "source_hash": "2" * 64,
        "verifier_base_image_id": "sha256:" + "3" * 64,
        "derived_agent_image_id": "sha256:" + "4" * 64,
        "host_codex_sha256": "5" * 64,
        "agent_codex_sha256": "6" * 64,
        "agent_rg_sha256": "9" * 64,
        "toolchain_profile_id": "cva6-verilator-v1",
        "allowlisted_artifacts": [
            {"path": "/usr/bin/make", "sha256": "7" * 64, "role": "build_tool"},
            {"path": "/tools/verilator/bin/verilator", "sha256": "8" * 64, "role": "simulator"},
        ],
        "security_scan_id": "6" * 64,
    }
    lock = build_hwe_agent_image_lock(**values)
    assert lock.format_id == "verigym_hwe_agent_image_lock_v2"
    assert lock.collection_profile_id == "hwe_standard_v2"
    assert lock.tool_contract_id == "hwe_native_shell_v2"
    assert lock.codex_version == "codex-cli 0.147.0"
    assert lock.security_scan_passed is True
    assert lock.lock_hash == content_hash(lock.model_dump(mode="json", exclude={"lock_hash"}))

    legacy = build_hwe_agent_image_lock(
        **values,
        format_id="verigym_hwe_agent_image_lock_v1",
        collection_profile_id="hwe_standard_v1",
        tool_contract_id="hwe_native_shell_v1",
    )
    assert legacy.format_id == "verigym_hwe_agent_image_lock_v1"
    assert legacy.collection_profile_id == "hwe_standard_v1"


def test_hwe_image_builder_sanitizes_inherited_base_environment() -> None:
    script = Path("scripts/build_cva6_hwe_agent_image.sh").read_text(encoding="utf-8")
    assert "sanitize_docker_image_environment.py" in script
    assert "--network none" in script
    assert "--environment 'CODEX_HOME=/tmp/verigym-codex-home'" not in script
    assert "--environment 'TMPDIR=/tmp'" in script
    assert "unsanitized_agent_image_id" in script


def _assistant_call(call_id: str, name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(
                        arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    ),
                },
            }
        ],
    }
