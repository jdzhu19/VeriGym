from __future__ import annotations

import os
import sys
from dataclasses import replace

import pytest

from verigym.core.errors import PathPolicyError
from verigym.core.repository_observation import BOUNDED_REPOSITORY_OBSERVATION_POLICY
from verigym.core.workspace import WorkspacePolicy, copy_tree_safely
from verigym.runtimes.local import LocalRuntime
from verigym.schemas.common import ErrorCategory
from verigym.schemas.runtime import SessionSpec
from verigym.schemas.tool import CommandSpec
from verigym.tools.base import ToolContext
from verigym.tools.file_tools import (
    FileApplyPatchTool,
    FileCodexPatchTool,
    FileListTool,
    FileReadTool,
    FileSearchTool,
    FileWriteTool,
)


@pytest.fixture
def local_session(tmp_path):
    source = tmp_path / "source"
    (source / "rtl").mkdir(parents=True)
    (source / "hidden").mkdir()
    (source / "rtl" / "counter.v").write_text("old\n", encoding="utf-8")
    (source / "README.md").write_text("read only\n", encoding="utf-8")
    (source / "hidden" / "test.sv").write_text("secret\n", encoding="utf-8")
    session = LocalRuntime().create_session(
        SessionSpec(source_dir=str(source), label="test", max_output_bytes=32)
    )
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def policy() -> WorkspacePolicy:
    return WorkspacePolicy(
        editable_globs=("rtl/**/*.v",),
        readonly_globs=("README.md",),
        excluded_globs=("hidden", "hidden/**"),
        max_changed_files=1,
        max_patch_lines=20,
    )


def test_file_tools_allow_declared_edit_and_reject_other_paths(local_session, policy) -> None:
    context = ToolContext(session=local_session, workspace_policy=policy, max_output_bytes=100)
    write = FileWriteTool()
    allowed = write.execute({"path": "rtl/counter.v", "content": "new\n"}, context)
    assert allowed.success
    assert local_session.read_file("rtl/counter.v") == b"new\n"
    denied = write.execute({"path": "README.md", "content": "changed"}, context)
    assert not denied.success
    assert denied.category == ErrorCategory.PERMISSION_DENIED
    traversal = FileReadTool().execute({"path": "../outside"}, context)
    assert not traversal.success
    assert traversal.category == ErrorCategory.PERMISSION_DENIED


def test_hidden_path_is_denied_without_disclosing_contents(local_session, policy) -> None:
    result = FileReadTool().execute(
        {"path": "hidden/test.sv"},
        ToolContext(session=local_session, workspace_policy=policy),
    )
    assert not result.success
    assert result.category == ErrorCategory.PERMISSION_DENIED
    assert "secret" not in result.stdout + result.stderr + result.message


def test_bounded_read_range_error_stays_an_invalid_request(local_session, policy) -> None:
    result = FileReadTool().execute(
        {"path": "rtl/counter.v", "start_line": 2},
        ToolContext(
            session=local_session,
            workspace_policy=policy,
            observation_policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
        ),
    )

    assert not result.success
    assert result.category == ErrorCategory.INVALID_REQUEST
    assert "start_line is outside the file" in result.message


@pytest.mark.parametrize("concise", [None, True])
def test_bounded_empty_file_read_succeeds(local_session, policy, concise) -> None:
    local_session.write_file("rtl/empty.v", b"")
    result = FileReadTool().execute(
        {"path": "rtl/empty.v", "concise": concise},
        ToolContext(
            session=local_session,
            workspace_policy=policy,
            observation_policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
        ),
    )

    assert result.success is True
    assert result.stdout == ""
    assert result.metadata["line_count"] == 0
    assert result.metadata["line_range"] == [0, 0]


def test_apply_patch_enforces_context_and_edit_glob(local_session, policy) -> None:
    context = ToolContext(session=local_session, workspace_policy=policy)
    patch = "--- a/rtl/counter.v\n+++ b/rtl/counter.v\n@@ -1 +1 @@\n-old\n+new\n"
    result = FileApplyPatchTool().execute({"patch": patch}, context)
    assert result.success
    assert local_session.read_file("rtl/counter.v") == b"new\n"
    outside = "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-read only\n+oops\n"
    result = FileApplyPatchTool().execute({"patch": outside}, context)
    assert not result.success
    assert local_session.read_file("README.md") == b"read only\n"


def test_codex_patch_compatibility_preserves_workspace_policy(local_session, policy) -> None:
    context = ToolContext(session=local_session, workspace_policy=policy)
    patch = """*** Begin Patch
*** Update File: rtl/counter.v
@@
-old
+new
*** End Patch"""

    strict = FileApplyPatchTool().execute({"patch": patch}, context)
    assert not strict.success
    assert local_session.read_file("rtl/counter.v") == b"old\n"

    compatible = FileCodexPatchTool().execute({"patch": patch}, context)
    assert compatible.success
    assert local_session.read_file("rtl/counter.v") == b"new\n"

    outside = """*** Begin Patch
*** Update File: README.md
@@
-read only
+changed
*** End Patch"""
    denied = FileCodexPatchTool().execute({"patch": outside}, context)
    assert not denied.success
    assert denied.category == ErrorCategory.PERMISSION_DENIED
    assert local_session.read_file("README.md") == b"read only\n"


def test_symlink_escape_is_rejected(tmp_path, local_session, policy) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    os.symlink(outside, local_session.root / "rtl" / "escape.v")
    result = FileReadTool().execute(
        {"path": "rtl/escape.v"},
        ToolContext(session=local_session, workspace_policy=policy),
    )
    assert not result.success
    assert result.category == ErrorCategory.PERMISSION_DENIED
    assert "outside" not in result.stdout
    listed = FileListTool().execute(
        {"path": "rtl/escape.v"},
        ToolContext(session=local_session, workspace_policy=policy),
    )
    assert not listed.success
    searched = FileSearchTool().execute(
        {"path": "rtl/escape.v", "query": "outside"},
        ToolContext(session=local_session, workspace_policy=policy),
    )
    assert not searched.success


def test_listing_a_workspace_file_is_recoverable_invalid_request(local_session, policy) -> None:
    result = FileListTool().execute(
        {"path": "rtl/counter.v"},
        ToolContext(session=local_session, workspace_policy=policy),
    )

    assert not result.success
    assert result.category == ErrorCategory.INVALID_REQUEST
    assert result.message == "path is not a directory"


def test_safe_copy_refuses_source_symlinks(tmp_path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    os.symlink(tmp_path, source / "escape")
    with pytest.raises(PathPolicyError, match="symlink"):
        copy_tree_safely(source, destination)


def test_safe_copy_can_preserve_canonical_modes_under_restrictive_umask(tmp_path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    regular = source / "design.sv"
    executable = source / "check.sh"
    regular.write_text("module design; endmodule\n", encoding="utf-8")
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    regular.chmod(0o644)
    executable.chmod(0o755)

    previous_umask = os.umask(0o077)
    try:
        copy_tree_safely(source, destination, preserve_safe_file_modes=True)
    finally:
        os.umask(previous_umask)

    assert destination.joinpath("design.sv").stat().st_mode & 0o7777 == 0o644
    assert destination.joinpath("check.sh").stat().st_mode & 0o7777 == 0o755


def test_safe_copy_rejects_unsafe_modes_when_preservation_is_requested(tmp_path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    unsafe = source / "design.sv"
    unsafe.write_text("module design; endmodule\n", encoding="utf-8")
    unsafe.chmod(0o666)

    with pytest.raises(PathPolicyError, match="unsafe file permissions"):
        copy_tree_safely(source, destination, preserve_safe_file_modes=True)


def test_local_runtime_bounds_output_and_times_out(local_session) -> None:
    output = local_session.execute(
        CommandSpec(
            argv=[sys.executable, "-c", "print('x' * 1000)"],
            timeout_s=5,
        )
    )
    assert output.output_truncated
    assert len(output.stdout.encode()) <= 32
    timeout = local_session.execute(
        CommandSpec(
            argv=[sys.executable, "-c", "import time; time.sleep(2)"],
            timeout_s=1,
        )
    )
    assert timeout.timed_out


def test_failed_workspace_size_check_rolls_back_write(local_session, policy) -> None:
    baseline_size = sum(
        path.stat().st_size
        for path in local_session.root.rglob("*")
        if path.is_file() and ".verigym_internal" not in path.parts
    )
    bounded_policy = replace(policy, max_workspace_bytes=baseline_size)
    result = FileWriteTool().execute(
        {"path": "rtl/counter.v", "content": "far too large\n" * 20},
        ToolContext(session=local_session, workspace_policy=bounded_policy),
    )
    assert not result.success
    assert result.category == ErrorCategory.PERMISSION_DENIED
    assert local_session.read_file("rtl/counter.v") == b"old\n"
