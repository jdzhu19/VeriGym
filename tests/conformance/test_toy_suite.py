from __future__ import annotations

from verigym.suites.toy_rtl.adapter import ToyRtlSuite


def test_toy_source_layout_and_cases_are_valid() -> None:
    suite = ToyRtlSuite()
    report = suite.validate_source()
    assert report.valid, report.errors
    references = list(suite.discover())
    assert [reference.id for reference in references] == [
        "toy-rtl/and-gate-basic",
        "toy-rtl/counter-basic",
    ]
    tasks = [suite.load_task(reference) for reference in references]
    assert all(task.source.license == "Apache-2.0" for task in tasks)
    cases = list(suite.conformance_cases())
    assert {case.expected_resolved for case in cases} == {True, False}
    assert len(cases) == 4
