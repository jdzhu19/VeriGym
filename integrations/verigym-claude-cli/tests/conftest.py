from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def short_broker_root() -> Iterator[Path]:
    """Create a private root short enough for the broker's Unix socket."""
    scratch_root = Path(
        os.environ.get("VERIGYM_TEST_SCRATCH_ROOT", tempfile.gettempdir())
    ).resolve()
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vgc-", dir=scratch_root) as raw_root:
        root = Path(raw_root)
        root.chmod(0o700)
        assert len(os.fsencode(root)) <= 72
        yield root
