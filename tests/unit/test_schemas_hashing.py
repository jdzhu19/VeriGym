from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from verigym.core.hashing import canonical_json, content_hash, hash_directory
from verigym.schemas.task import VeriTask
from verigym.schemas.verifier import VerifierGraph, VerifierNode
from verigym.suites.toy_rtl.adapter import ToyRtlSuite


def load_counter_task() -> VeriTask:
    suite = ToyRtlSuite()
    return suite.load_task(next(iter(suite.discover())))


def test_task_round_trip_is_strict_and_stable() -> None:
    task = load_counter_task()
    round_tripped = VeriTask.model_validate_json(task.model_dump_json())
    assert round_tripped == task
    assert content_hash(round_tripped) == content_hash(task)
    document = json.loads(task.model_dump_json())
    document["misspelled_field"] = True
    with pytest.raises(ValidationError, match="misspelled_field"):
        VeriTask.model_validate(document)


def test_canonical_hash_ignores_mapping_insertion_order() -> None:
    left = {"b": [2, 1], "a": {"z": True, "x": None}}
    right = {"a": {"x": None, "z": True}, "b": [2, 1]}
    assert canonical_json(left) == canonical_json(right)
    assert content_hash(left) == content_hash(right)


def test_verifier_graph_rejects_cycles_and_unknown_dependencies() -> None:
    common = {"plugin": "iverilog.compile", "visibility": "verifier_only", "request": {}}
    with pytest.raises(ValidationError, match="cycle"):
        VerifierGraph(
            nodes=[
                VerifierNode(id="a", depends_on=["b"], **common),
                VerifierNode(id="b", depends_on=["a"], **common),
            ]
        )
    with pytest.raises(ValidationError, match="unknown dependencies"):
        VerifierGraph(nodes=[VerifierNode(id="a", depends_on=["missing"], **common)])


def test_task_cross_references_required_verifier_nodes() -> None:
    task = load_counter_task()
    document = task.model_dump(mode="json")
    document["scoring"]["correctness_required_nodes"].append("does_not_exist")
    with pytest.raises(ValidationError, match="correctness nodes missing"):
        VeriTask.model_validate(document)


def test_directory_hash_can_exclude_generated_cache_content(tmp_path) -> None:
    root = tmp_path / "source"
    cache = root / "hidden" / "__pycache__"
    cache.mkdir(parents=True)
    (root / "task.yaml").write_text("stable", encoding="utf-8")
    before = hash_directory(root, excluded_names={"__pycache__"})
    (cache / "generated.pyc").write_bytes(b"nondeterministic-bytecode")
    after = hash_directory(root, excluded_names={"__pycache__"})
    assert before == after
