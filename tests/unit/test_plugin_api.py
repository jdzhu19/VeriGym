from __future__ import annotations


def test_suite_authoring_contract_is_available_from_plugin_api() -> None:
    from verigym import plugin_api

    expected = {
        "AssetRef",
        "BudgetSpec",
        "Candidate",
        "ConfigurationError",
        "ConformanceCase",
        "InteractionSpec",
        "ObservationPolicy",
        "RuntimeRequirement",
        "ScoringSpec",
        "SourceSpec",
        "SubmissionPolicy",
        "SuiteSourceConfig",
        "SuiteSourceSnapshot",
        "TaskType",
        "ToolRequirement",
        "ToolchainProfile",
        "ValidationIssue",
        "VerifierGraph",
        "VerifierNode",
        "WorkspaceSpec",
    }

    assert expected <= set(plugin_api.__all__)
    for name in expected:
        assert getattr(plugin_api, name) is not None
