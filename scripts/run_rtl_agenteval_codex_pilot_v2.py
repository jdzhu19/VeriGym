#!/usr/bin/env python3
"""Finalize historical evidence, qualify RTL-Repo v3, and run the frozen pilot v7."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import run_rtl_agenteval_codex_gymfix_diagnostic as gymfix
import run_rtl_agenteval_codex_pilot as pilot_v1
import run_rtl_agenteval_codex_smoke as smoke
from verigym_codex_cli.agenteval_agent import (
    _SCORING_EVENT_FAILURE_SUBCATEGORIES as _CURRENT_SCORING_EVENT_FAILURE_SUBCATEGORIES,
)
from verigym_codex_cli.agenteval_config import (
    AGENTEVAL_AGENT_VERSION_HASH as _CURRENT_AGENT_VERSION_HASH,
)
from verigym_codex_cli.agenteval_config import (
    AGENTEVAL_AGENT_VERSION_ID as _CURRENT_AGENT_VERSION_ID,
)
from verigym_codex_cli.agenteval_config import AGENTEVAL_PROMPT_HASH as _CURRENT_PROMPT_HASH
from verigym_codex_cli.agenteval_config import (
    AGENTEVAL_TOOL_POLICY_FINGERPRINT as _CURRENT_TOOL_POLICY_FINGERPRINT,
)
from verigym_codex_cli.events import validate_scoring_mcp_stream
from verigym_rtl_repo import (
    AGENT_EVAL_V2_SUITE_VERSION,
    AGENT_EVAL_V3_COMPLETION_CONTRACT,
    AGENT_EVAL_V3_SUITE_VERSION,
)
from verigym_rtl_repo.dataset import (
    AGENT_EVAL_V2_VARIANT,
    AGENT_EVAL_V3_VARIANT,
    CONTEXT_CLASSIFICATION_RULE,
)

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.core.loaders import load_model
from verigym.core.orchestrator import VeriGym
from verigym.experiments.state import atomic_dump_json
from verigym.profiles.identity import resolved_profile_component_hashes
from verigym.protocols.repository_action import (
    canonical_tool_observation,
    repository_tool_definitions,
)
from verigym.schemas.common import InteractionMode
from verigym.schemas.run import RunConfig, RunManifest, RunResult
from verigym.schemas.score import ScoreCard
from verigym.schemas.suite import SuiteSourceConfig

_QUALIFICATION_ID = "rtl-agenteval-codex-gpt54-xhigh-eventfix-qualification-v1"
_PILOT_V2_ID = "rtl-agenteval-codex-gpt54-xhigh-pilot-v2"
_QUALIFICATION_V2_ID = "rtl-agenteval-codex-gpt54-xhigh-transportfix-qualification-v2"
_PILOT_V3_ID = "rtl-agenteval-codex-gpt54-xhigh-pilot-v3"
_QUALIFICATION_V3_ID = "rtl-agenteval-codex-gpt54-xhigh-finalizationfix-qualification-v3"
_PILOT_V4_ID = "rtl-agenteval-codex-gpt54-xhigh-pilot-v4"
_QUALIFICATION_V4_ID = "rtl-agenteval-codex-gpt54-xhigh-brokerattest-qualification-v4"
_PILOT_V5_ID = "rtl-agenteval-codex-gpt54-xhigh-pilot-v5"
_QUALIFICATION_V5_ID = "rtl-agenteval-codex-gpt54-xhigh-directmcp-qualification-v5"
_PILOT_V6_ID = "rtl-agenteval-codex-gpt54-xhigh-pilot-v6"
_QUALIFICATION_V6_ID = "rtl-agenteval-codex-gpt54-xhigh-nextline-qualification-v6"
_PILOT_V7_ID = "rtl-agenteval-codex-gpt54-xhigh-pilot-v7"
_V6_AGENT_VERSION_ID = "codex-cli-agenteval-gpt54-xhigh-v6"
_V6_AGENT_VERSION_HASH = "f4399e9302d4747127452340a73b68ea50b96688c70e54be1e8bc63dcc44a15f"
_V6_PROMPT_HASH = "bd96dbf5defd6203d4939873f92817817bd5593750cd6e292a4c0240135edc5c"
_V6_TOOL_POLICY_FINGERPRINT = "7090e133a5e3a95742c129ee3510d3c1bd7d41d65eeabb6bac31f3ef94fba412"
_V7_AGENT_VERSION_ID = "codex-cli-agenteval-gpt54-xhigh-v7"
_V7_AGENT_VERSION_HASH = "676eed177f38cf8c9b5d41259259496ea1915e819e7cee3366a129de92c05651"
_V7_PROMPT_HASH = "d94cdc20bdb61c11715f0934bae32f7ff1daa5c2634c948e17669622100ec170"
_V7_TOOL_POLICY_FINGERPRINT = "defc1e4a3ceb8832d14c86668537e004b43f51cc72b29da154328237ac71cf2f"
_V8_AGENT_VERSION_ID = "codex-cli-agenteval-gpt54-xhigh-v8"
_V8_AGENT_VERSION_HASH = "cf8d02f980633aa59a1b38611db41cc2d8d8bd95f4b0ec4a1c60e837a286cd04"
_V8_PROMPT_HASH = "fe8bc9e5f2e3b91443bb9130e51b4de7cde4be5fe9d2b4ba97bc16417d0b2e79"
_V8_TOOL_POLICY_FINGERPRINT = "699e2bb43e1cc7a19c8e26642ee25de1748dd210baab4738635a71a16091bcd8"
_V9_AGENT_VERSION_ID = "codex-cli-agenteval-gpt54-xhigh-v9"
_V9_AGENT_VERSION_HASH = "166445fb1af0f822aaf1fa5654e79ec2223bd3f6d3c38b6f3221c77f09d596a9"
_V9_PROMPT_HASH = "fe8bc9e5f2e3b91443bb9130e51b4de7cde4be5fe9d2b4ba97bc16417d0b2e79"
_V9_TOOL_POLICY_FINGERPRINT = "64d9a512ed7b7baee6ba186708296751cc01619596aff2f093373c3d77844790"
_SCORING_EVENT_FAILURE_SUBCATEGORIES = (
    frozenset(
        {
            "scoring_event_blank_line",
            "scoring_event_broker_not_finished",
            "scoring_event_finish_count",
            "scoring_event_invalid_action",
            "scoring_event_invalid_event",
            "scoring_event_malformed_item",
            "scoring_event_malformed_json",
            "scoring_event_mcp_outside_verigym",
            "scoring_event_missing_finish",
            "scoring_event_missing_observation",
            "scoring_event_multiple_post_finish_messages",
            "scoring_event_non_mcp_tool",
            "scoring_event_parse_incomplete",
            "scoring_event_post_finish_tool",
            "scoring_event_process_exit",
            "scoring_event_provider_error",
            "scoring_event_terminal_missing",
            "scoring_event_tool_count_mismatch",
            "scoring_event_unsupported_event",
            "scoring_event_unsupported_item",
            "scoring_event_unspecified",
        }
    )
    | _CURRENT_SCORING_EVENT_FAILURE_SUBCATEGORIES
)
_EXPERIMENTS = Path("/data/jzhu484/Agent/experiments")
_GYMFIX_SUMMARY = _EXPERIMENTS / gymfix._CAMPAIGN_ID / "summary.json"
_QUALIFICATION_SUMMARY = _EXPERIMENTS / _QUALIFICATION_ID / "summary.json"
_QUALIFICATION_V2_SUMMARY = _EXPERIMENTS / _QUALIFICATION_V2_ID / "summary.json"
_QUALIFICATION_V3_SUMMARY = _EXPERIMENTS / _QUALIFICATION_V3_ID / "summary.json"
_QUALIFICATION_V4_SUMMARY = _EXPERIMENTS / _QUALIFICATION_V4_ID / "summary.json"
_QUALIFICATION_V5_SUMMARY = _EXPERIMENTS / _QUALIFICATION_V5_ID / "summary.json"
_QUALIFICATION_V6_SUMMARY = _EXPERIMENTS / _QUALIFICATION_V6_ID / "summary.json"
_REFERENCE_URLS = (
    "https://learn.chatgpt.com/docs/non-interactive-mode",
    "https://github.com/openai/codex/blob/rust-v0.147.0/"
    "codex-rs/exec/src/event_processor_with_jsonl_output.rs",
    "https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/exec/src/exec_events.rs",
    "https://github.com/openai/codex/issues/24536",
    "https://github.com/openai/codex/issues/14691",
    "https://github.com/openai/codex/issues/23131",
    "https://github.com/openai/codex/issues/5028",
    "https://github.com/openai/codex/issues/16685",
    "https://arxiv.org/abs/2405.17378",
    "https://github.com/AUCOHL/RTL-Repo",
    "https://github.com/HPAI-BSC/TuRTLe",
)
_PATH_CATEGORIES = frozenset(
    {
        "absolute",
        "traversal",
        "outside_editable",
        "readonly",
        "symlink",
        "hardlink",
        "hidden_or_protected",
        "unspecified",
    }
)
_TOOL_NAMES = frozenset(
    definition["name"] for definition in repository_tool_definitions(dialect="mcp")
)


@dataclass(frozen=True)
class CampaignRunSpec:
    run_id: str
    task_id: str
    source_key: str
    profile_name: str | None = None
    ppa: bool = False


@dataclass(frozen=True)
class CampaignDefinition:
    key: str
    campaign_id: str
    predecessor: Path
    opt_in: str
    diagnostic_only: bool
    specs: tuple[CampaignRunSpec, ...]
    agent_version_id: str
    agent_version_hash: str
    prompt_hash: str
    tool_policy_fingerprint: str
    prompt_contract_id: str
    bounded_event_categories_safe: bool = False
    rtl_repo_variant: str = AGENT_EVAL_V2_VARIANT
    rtl_repo_suite_version: str = AGENT_EVAL_V2_SUITE_VERSION
    rtl_repo_projection_version: str = "v2"
    rtl_repo_completion_contract: str | None = None

    @property
    def output(self) -> Path:
        return _EXPERIMENTS / self.campaign_id

    @property
    def process_count(self) -> int:
        return len(self.specs)

    @property
    def ppa_run_ids(self) -> frozenset[str]:
        return frozenset(spec.run_id for spec in self.specs if spec.ppa)


_QUALIFICATION_SPECS = (
    CampaignRunSpec(
        "01-counter-dc",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_dc",
        True,
    ),
    CampaignRunSpec(
        "02-rtl-repo-test-000003",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000003",
        "rtl_repo",
    ),
    CampaignRunSpec(
        "03-rtl-repo-test-000004",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000004",
        "rtl_repo",
    ),
)

_QUALIFICATION_V2_SPECS = (
    CampaignRunSpec(
        "01-counter-open",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_open",
        True,
    ),
    CampaignRunSpec(
        "02-rtl-repo-test-000002",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000002",
        "rtl_repo",
    ),
    CampaignRunSpec(
        "03-rtl-repo-test-000005",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000005",
        "rtl_repo",
    ),
)

_QUALIFICATION_V3_SPECS = (
    CampaignRunSpec(
        "01-counter-open",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_open",
        True,
    ),
    CampaignRunSpec(
        "02-rtl-repo-test-000003",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000003",
        "rtl_repo",
    ),
    CampaignRunSpec(
        "03-rtl-repo-test-000004",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000004",
        "rtl_repo",
    ),
)

_QUALIFICATION_V4_SPECS = _QUALIFICATION_V3_SPECS
_QUALIFICATION_V5_SPECS = _QUALIFICATION_V3_SPECS

_QUALIFICATION_V6_SPECS = (
    CampaignRunSpec(
        "01-counter-open",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_open",
        True,
    ),
    CampaignRunSpec(
        "02-rtl-repo-test-000003",
        f"rtl-repo/{AGENT_EVAL_V3_VARIANT}/test-000003",
        "rtl_repo",
    ),
    CampaignRunSpec(
        "03-rtl-repo-test-000004",
        f"rtl-repo/{AGENT_EVAL_V3_VARIANT}/test-000004",
        "rtl_repo",
    ),
)

_PILOT_V2_SPECS = (
    CampaignRunSpec(
        "01-counter-open",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_open",
        True,
    ),
    CampaignRunSpec(
        "02-counter-dc",
        "rtllm/counter_12_agent_eval_v1",
        "counter",
        "counter_dc",
        True,
    ),
    CampaignRunSpec(
        "03-up-down-open",
        "rtllm/up_down_counter_agent_eval_v1",
        "up_down",
        "up_down_open",
        True,
    ),
    CampaignRunSpec(
        "04-up-down-dc",
        "rtllm/up_down_counter_agent_eval_v1",
        "up_down",
        "up_down_dc",
        True,
    ),
    CampaignRunSpec(
        "05-verilog-eval-prob005-notgate",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob005_notgate",
        "verilog_eval",
    ),
    CampaignRunSpec(
        "06-verilog-eval-prob007-wire",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob007_wire",
        "verilog_eval",
    ),
    CampaignRunSpec(
        "07-verilog-eval-prob009-popcount3",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob009_popcount3",
        "verilog_eval",
    ),
    CampaignRunSpec(
        "08-verilog-eval-prob011-norgate",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob011_norgate",
        "verilog_eval",
    ),
    CampaignRunSpec(
        "09-verilog-eval-prob012-xnorgate",
        "verilog-eval/v2-spec-to-rtl-agent-eval-v1/Prob012_xnorgate",
        "verilog_eval",
    ),
    CampaignRunSpec(
        "10-rtl-repo-test-000039",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000039",
        "rtl_repo",
    ),
    CampaignRunSpec(
        "11-rtl-repo-test-000065",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000065",
        "rtl_repo",
    ),
    CampaignRunSpec(
        "12-rtl-repo-test-000067",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000067",
        "rtl_repo",
    ),
    CampaignRunSpec(
        "13-rtl-repo-test-000068",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000068",
        "rtl_repo",
    ),
    CampaignRunSpec(
        "14-rtl-repo-test-000069",
        f"rtl-repo/{AGENT_EVAL_V2_VARIANT}/test-000069",
        "rtl_repo",
    ),
)

_PILOT_V7_SPECS = tuple(
    CampaignRunSpec(
        run_id=spec.run_id,
        task_id=(
            spec.task_id.replace(AGENT_EVAL_V2_VARIANT, AGENT_EVAL_V3_VARIANT)
            if spec.source_key == "rtl_repo"
            else spec.task_id
        ),
        source_key=spec.source_key,
        profile_name=spec.profile_name,
        ppa=spec.ppa,
    )
    for spec in _PILOT_V2_SPECS
)

_DEFINITIONS = {
    "qualification": CampaignDefinition(
        key="qualification",
        campaign_id=_QUALIFICATION_ID,
        predecessor=_GYMFIX_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_EVENTFIX_QUALIFICATION",
        diagnostic_only=True,
        specs=_QUALIFICATION_SPECS,
        agent_version_id=_V6_AGENT_VERSION_ID,
        agent_version_hash=_V6_AGENT_VERSION_HASH,
        prompt_hash=_V6_PROMPT_HASH,
        tool_policy_fingerprint=_V6_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v4",
    ),
    "pilot-v2": CampaignDefinition(
        key="pilot-v2",
        campaign_id=_PILOT_V2_ID,
        predecessor=_QUALIFICATION_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V2",
        diagnostic_only=False,
        specs=_PILOT_V2_SPECS,
        agent_version_id=_V6_AGENT_VERSION_ID,
        agent_version_hash=_V6_AGENT_VERSION_HASH,
        prompt_hash=_V6_PROMPT_HASH,
        tool_policy_fingerprint=_V6_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v4",
    ),
    "qualification-v2": CampaignDefinition(
        key="qualification-v2",
        campaign_id=_QUALIFICATION_V2_ID,
        predecessor=_QUALIFICATION_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_TRANSPORTFIX_QUALIFICATION_V2",
        diagnostic_only=True,
        specs=_QUALIFICATION_V2_SPECS,
        agent_version_id=_V7_AGENT_VERSION_ID,
        agent_version_hash=_V7_AGENT_VERSION_HASH,
        prompt_hash=_V7_PROMPT_HASH,
        tool_policy_fingerprint=_V7_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v5",
    ),
    "pilot-v3": CampaignDefinition(
        key="pilot-v3",
        campaign_id=_PILOT_V3_ID,
        predecessor=_QUALIFICATION_V2_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V3",
        diagnostic_only=False,
        specs=_PILOT_V2_SPECS,
        agent_version_id=_V7_AGENT_VERSION_ID,
        agent_version_hash=_V7_AGENT_VERSION_HASH,
        prompt_hash=_V7_PROMPT_HASH,
        tool_policy_fingerprint=_V7_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v5",
    ),
    "qualification-v3": CampaignDefinition(
        key="qualification-v3",
        campaign_id=_QUALIFICATION_V3_ID,
        predecessor=_QUALIFICATION_V2_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_FINALIZATIONFIX_QUALIFICATION_V3",
        diagnostic_only=True,
        specs=_QUALIFICATION_V3_SPECS,
        agent_version_id=_V8_AGENT_VERSION_ID,
        agent_version_hash=_V8_AGENT_VERSION_HASH,
        prompt_hash=_V8_PROMPT_HASH,
        tool_policy_fingerprint=_V8_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v6",
        bounded_event_categories_safe=True,
    ),
    "pilot-v4": CampaignDefinition(
        key="pilot-v4",
        campaign_id=_PILOT_V4_ID,
        predecessor=_QUALIFICATION_V3_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V4",
        diagnostic_only=False,
        specs=_PILOT_V2_SPECS,
        agent_version_id=_V8_AGENT_VERSION_ID,
        agent_version_hash=_V8_AGENT_VERSION_HASH,
        prompt_hash=_V8_PROMPT_HASH,
        tool_policy_fingerprint=_V8_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v6",
        bounded_event_categories_safe=True,
    ),
    "qualification-v4": CampaignDefinition(
        key="qualification-v4",
        campaign_id=_QUALIFICATION_V4_ID,
        predecessor=_QUALIFICATION_V3_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_BROKERATTEST_QUALIFICATION_V4",
        diagnostic_only=True,
        specs=_QUALIFICATION_V4_SPECS,
        agent_version_id=_V9_AGENT_VERSION_ID,
        agent_version_hash=_V9_AGENT_VERSION_HASH,
        prompt_hash=_V9_PROMPT_HASH,
        tool_policy_fingerprint=_V9_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v6",
        bounded_event_categories_safe=True,
    ),
    "pilot-v5": CampaignDefinition(
        key="pilot-v5",
        campaign_id=_PILOT_V5_ID,
        predecessor=_QUALIFICATION_V4_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V5",
        diagnostic_only=False,
        specs=_PILOT_V2_SPECS,
        agent_version_id=_V9_AGENT_VERSION_ID,
        agent_version_hash=_V9_AGENT_VERSION_HASH,
        prompt_hash=_V9_PROMPT_HASH,
        tool_policy_fingerprint=_V9_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v6",
        bounded_event_categories_safe=True,
    ),
    "qualification-v5": CampaignDefinition(
        key="qualification-v5",
        campaign_id=_QUALIFICATION_V5_ID,
        predecessor=_QUALIFICATION_V4_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_DIRECTMCP_QUALIFICATION_V5",
        diagnostic_only=True,
        specs=_QUALIFICATION_V5_SPECS,
        agent_version_id=_CURRENT_AGENT_VERSION_ID,
        agent_version_hash=_CURRENT_AGENT_VERSION_HASH,
        prompt_hash=_CURRENT_PROMPT_HASH,
        tool_policy_fingerprint=_CURRENT_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v6",
        bounded_event_categories_safe=True,
    ),
    "pilot-v6": CampaignDefinition(
        key="pilot-v6",
        campaign_id=_PILOT_V6_ID,
        predecessor=_QUALIFICATION_V5_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V6",
        diagnostic_only=False,
        specs=_PILOT_V2_SPECS,
        agent_version_id=_CURRENT_AGENT_VERSION_ID,
        agent_version_hash=_CURRENT_AGENT_VERSION_HASH,
        prompt_hash=_CURRENT_PROMPT_HASH,
        tool_policy_fingerprint=_CURRENT_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v6",
        bounded_event_categories_safe=True,
    ),
    "qualification-v6": CampaignDefinition(
        key="qualification-v6",
        campaign_id=_QUALIFICATION_V6_ID,
        predecessor=_QUALIFICATION_V5_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_NEXTLINE_QUALIFICATION_V6",
        diagnostic_only=True,
        specs=_QUALIFICATION_V6_SPECS,
        agent_version_id=_CURRENT_AGENT_VERSION_ID,
        agent_version_hash=_CURRENT_AGENT_VERSION_HASH,
        prompt_hash=_CURRENT_PROMPT_HASH,
        tool_policy_fingerprint=_CURRENT_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v6",
        bounded_event_categories_safe=True,
        rtl_repo_variant=AGENT_EVAL_V3_VARIANT,
        rtl_repo_suite_version=AGENT_EVAL_V3_SUITE_VERSION,
        rtl_repo_projection_version="v3",
        rtl_repo_completion_contract=AGENT_EVAL_V3_COMPLETION_CONTRACT,
    ),
    "pilot-v7": CampaignDefinition(
        key="pilot-v7",
        campaign_id=_PILOT_V7_ID,
        predecessor=_QUALIFICATION_V6_SUMMARY,
        opt_in="VERIGYM_RUN_RTL_AGENT_EVAL_PILOT_V7",
        diagnostic_only=False,
        specs=_PILOT_V7_SPECS,
        agent_version_id=_CURRENT_AGENT_VERSION_ID,
        agent_version_hash=_CURRENT_AGENT_VERSION_HASH,
        prompt_hash=_CURRENT_PROMPT_HASH,
        tool_policy_fingerprint=_CURRENT_TOOL_POLICY_FINGERPRINT,
        prompt_contract_id="repository_action_v2_prompt_v6",
        bounded_event_categories_safe=True,
        rtl_repo_variant=AGENT_EVAL_V3_VARIANT,
        rtl_repo_suite_version=AGENT_EVAL_V3_SUITE_VERSION,
        rtl_repo_projection_version="v3",
        rtl_repo_completion_contract=AGENT_EVAL_V3_COMPLETION_CONTRACT,
    ),
}

CampaignInfrastructureError = smoke.CampaignInfrastructureError
PreparedProfile = smoke.PreparedProfile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", choices=sorted(_DEFINITIONS), default="qualification-v6")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--finalize-existing", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--predecessor-summary", type=Path)
    parser.add_argument("--site-work", type=Path, required=True)
    parser.add_argument("--broker-root", type=Path)
    parser.add_argument("--rtllm-source", type=Path, required=True)
    parser.add_argument("--verilog-eval-source", type=Path, required=True)
    parser.add_argument("--rtl-repo-source", type=Path, required=True)
    parser.add_argument("--pdk-root", type=Path, required=True)
    parser.add_argument("--dc-counter-profile", type=Path, required=True)
    parser.add_argument("--dc-up-down-profile", type=Path, required=True)
    parser.add_argument("--vcs-counter-profile", type=Path, required=True)
    parser.add_argument("--vcs-up-down-profile", type=Path, required=True)
    parser.add_argument("--image", default=smoke._IMAGE)
    parser.add_argument("--codex-binary", default="codex")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    definition = _DEFINITIONS[arguments.campaign]
    arguments.output = arguments.output or definition.output
    arguments.predecessor_summary = arguments.predecessor_summary or definition.predecessor
    arguments.broker_root = arguments.broker_root or Path(
        f"/data/jzhu484/Agent/.verigym-tmp/cb-ae-{definition.key.replace('-', '')}"
    )
    if arguments.finalize_existing:
        return _finalize_existing(arguments, definition)
    if definition.agent_version_id != _CURRENT_AGENT_VERSION_ID:
        raise ConfigurationError("historical AgentEval campaigns are finalization-only")

    site_work = smoke._new_path(arguments.site_work, "site-profile work directory")
    output = smoke._new_path(arguments.output, "experiment output")
    broker_root = smoke._new_path(arguments.broker_root, "Codex broker root")
    inputs = pilot_v1._inputs(arguments)
    profile_paths = pilot_v1._profile_paths(arguments)
    predecessor_path = smoke._regular_file(arguments.predecessor_summary, "predecessor summary")
    predecessor = _validate_predecessor(predecessor_path, definition)
    capability_path, capability, auth = smoke._codex_preflight(arguments.codex_binary, site_work)
    os.environ["VERIGYM_CODEX_CAPABILITY_FILE"] = str(capability_path)
    image_id = smoke._docker_image_id(arguments.image)
    docker_config = smoke._docker_config(arguments.image, image_id)

    registries = smoke._registries()
    service = VeriGym(registries)
    source_configs = _source_configs(inputs, definition)
    _validate_sources(service, source_configs, definition.specs)
    projection = _rtl_repo_v2_qualification(service, source_configs["rtl_repo"], definition.specs)
    broker_regression = gymfix._repository_broker_regression_qualification(
        service, _broker_regression_source_configs(source_configs, inputs)
    )
    event_contract = _scoring_event_contract_qualification(definition)
    prepared = smoke._prepare_profiles(
        registries,
        site_work=site_work,
        image=arguments.image,
        image_id=image_id,
        pdk_root=inputs["pdk"],
        dc_paths=profile_paths,
    )
    runtime_descriptor, qualifications = smoke._no_model_qualification(
        service,
        source_configs=source_configs,
        docker_config=docker_config,
        prepared=prepared,
        vcs_paths=profile_paths,
        scratch=site_work / "qualification",
    )
    qualifications["repository_broker_regression"] = broker_regression
    qualifications[f"rtl_repo_projection_{definition.rtl_repo_projection_version}"] = projection
    qualifications["scoring_event_contract"] = event_contract
    qualifications["predecessor"] = predecessor

    os.environ["VERIGYM_CODEX_BROKER_ROOT"] = str(smoke._broker_root(broker_root))
    configs = _frozen_run_configs(
        service,
        source_configs=source_configs,
        docker_config=docker_config,
        runtime_descriptor=runtime_descriptor,
        prepared=prepared,
        agent_options=_agent_options(capability, auth, definition),
        output=output / "runs",
        specs=definition.specs,
    )
    plan = _build_plan(
        definition,
        capability=capability,
        auth=auth,
        runtime_descriptor=runtime_descriptor,
        prepared=prepared,
        qualifications=qualifications,
        configs=configs,
        predecessor_path=predecessor_path,
    )

    if not arguments.execute:
        atomic_dump_json(site_work / "preflight-plan.json", plan)
        print(
            json.dumps(
                {
                    "status": "qualified_plan_only",
                    "campaign_id": definition.campaign_id,
                    "model_calls": 0,
                    "planned_codex_processes": definition.process_count,
                    "benchmark_score_claimed": False,
                },
                sort_keys=True,
            )
        )
        return 0
    if os.environ.get(definition.opt_in) != "1":
        raise ConfigurationError(f"execution requires {definition.opt_in}=1")

    output.mkdir(parents=True)
    (output / "runs").mkdir()
    (output / "evidence").mkdir()
    atomic_dump_json(output / "plan.json", plan)
    results = _execute_bounded(service, configs, output, definition)
    replay = smoke._offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_configs,
        profile_paths,
        inputs,
        definition.specs,
        site_paths=(site_work, broker_root, output, predecessor_path),
        bounded_event_categories_safe=definition.bounded_event_categories_safe,
    )
    redaction = _redaction_audit(results, definition.process_count)
    summary = _campaign_summary(results, replay, scan, redaction, definition)
    _persist_final_evidence(output, replay, scan, redaction, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["fully_successful"] else 2


def _source_configs(
    inputs: dict[str, Path], definition: CampaignDefinition | None = None
) -> dict[str, SuiteSourceConfig]:
    rtl_repo_variant = (
        definition.rtl_repo_variant if definition is not None else AGENT_EVAL_V2_VARIANT
    )
    return {
        "counter": SuiteSourceConfig(
            source_root=inputs["rtllm"], variant="counter_12_agent_eval_v1"
        ),
        "up_down": SuiteSourceConfig(
            source_root=inputs["rtllm"], variant="up_down_counter_agent_eval_v1"
        ),
        "verilog_eval": SuiteSourceConfig(
            source_root=inputs["verilog_eval"], variant="v2-spec-to-rtl-agent-eval-v1"
        ),
        "rtl_repo": SuiteSourceConfig(source_root=inputs["rtl_repo"], variant=rtl_repo_variant),
    }


def _broker_regression_source_configs(
    source_configs: dict[str, SuiteSourceConfig], inputs: dict[str, Path]
) -> dict[str, SuiteSourceConfig]:
    configs = dict(source_configs)
    configs["rtl_repo"] = SuiteSourceConfig(
        source_root=inputs["rtl_repo"], variant=AGENT_EVAL_V2_VARIANT
    )
    return configs


def _agent_options(capability: Any, auth: Any, definition: CampaignDefinition) -> dict[str, Any]:
    return {
        "model_id": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "max_process_time_s": 900,
        "max_output_bytes": 8 * 1024 * 1024,
        "allow_proxy_environment": bool(
            os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
        ),
        "expected_cli_version": smoke._EXPECTED_CLI_VERSION,
        "expected_cli_executable_sha256": smoke._EXPECTED_CODEX_SHA256,
        "expected_capability_fingerprint": capability.capability_fingerprint,
        "expected_prompt_hash": definition.prompt_hash,
        "expected_tool_policy_fingerprint": definition.tool_policy_fingerprint,
        "expected_requested_auth_mode": auth.requested_auth_mode,
        "expected_resolved_auth_mode": auth.resolved_auth_mode,
        "expected_auth_semantic_id": auth.auth_semantic_id,
        "prompt_contract_id": definition.prompt_contract_id,
        "scoring_agent_version_id": definition.agent_version_id,
        "scoring_agent_version_hash": definition.agent_version_hash,
    }


def _validate_sources(
    service: VeriGym,
    configs: dict[str, SuiteSourceConfig],
    specs: tuple[CampaignRunSpec, ...],
) -> None:
    checked: set[tuple[str, str]] = set()
    tasks = [
        (smoke._TASKS[0], "counter"),
        (smoke._TASKS[1], "up_down"),
        (smoke._TASKS[2], "verilog_eval"),
        *((spec.task_id, spec.source_key) for spec in specs),
    ]
    for task_id, key in tasks:
        if (task_id, key) in checked:
            continue
        checked.add((task_id, key))
        suite, task, assets = service.load_task(task_id, configs[key])
        report = suite.validate_source()
        if not report.valid or not Path(assets.visible_root).is_dir() or task.id != task_id:
            raise ConfigurationError(f"source qualification failed for {task_id}")


def _rtl_repo_v2_qualification(
    service: VeriGym,
    source_config: SuiteSourceConfig,
    specs: tuple[CampaignRunSpec, ...],
) -> dict[str, Any]:
    variant = source_config.variant
    if variant == AGENT_EVAL_V2_VARIANT:
        suite_version = AGENT_EVAL_V2_SUITE_VERSION
        projection_version = "v2"
        completion_contract = None
    elif variant == AGENT_EVAL_V3_VARIANT:
        suite_version = AGENT_EVAL_V3_SUITE_VERSION
        projection_version = "v3"
        completion_contract = AGENT_EVAL_V3_COMPLETION_CONTRACT
    else:
        raise ConfigurationError("RTL-Repo projection qualification requires v2 or v3")
    records: list[dict[str, Any]] = []
    for spec in specs:
        if spec.source_key != "rtl_repo":
            continue
        _suite, task, assets = service.load_task(spec.task_id, source_config)
        root = Path(assets.visible_root)
        try:
            index = json.loads(
                (root / "repository" / "context" / "index.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError("RTL-Repo context index is unreadable") from exc
        items = index.get("items") if isinstance(index, dict) else None
        if (
            task.suite_version != suite_version
            or task.metadata.get("projection_version") != projection_version
            or task.metadata.get("context_classification_rule") != CONTEXT_CLASSIFICATION_RULE
            or task.metadata.get("completion_contract") != completion_contract
            or index.get("completion_contract") != completion_contract
            or not isinstance(items, list)
            or len(items) != task.metadata.get("context_count")
        ):
            raise ConfigurationError("RTL-Repo task identity or index differs")
        totals = {"source": 0, "generated": 0}
        for ordinal, item in enumerate(items):
            if not isinstance(item, dict):
                raise ConfigurationError("RTL-Repo context item is malformed")
            expected_file = f"{ordinal:04d}.txt"
            classification = item.get("classification")
            payload = (root / "repository" / "context" / expected_file).read_bytes()
            if (
                item.get("file") != expected_file
                or classification not in totals
                or item.get("read_priority") != (0 if classification == "source" else 1)
                or item.get("utf8_bytes") != len(payload)
            ):
                raise ConfigurationError("RTL-Repo context ordering or byte count differs")
            try:
                payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ConfigurationError("RTL-Repo context is not UTF-8") from exc
            totals[classification] += len(payload)
        if (
            index.get("source_utf8_bytes") != totals["source"]
            or index.get("generated_utf8_bytes") != totals["generated"]
            or index.get("read_priority_order") != ["source", "generated"]
        ):
            raise ConfigurationError("RTL-Repo aggregate context bytes differ")
        visible_paths = {
            path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
        }
        if (
            any(path == "hidden" or path.startswith("hidden/") for path in visible_paths)
            or any(path == "verifier" or path.startswith("verifier/") for path in visible_paths)
            or "next_line" in index
            or "all_code" in index
            or any(hidden.mount_path in visible_paths for hidden in assets.hidden_assets)
        ):
            raise ConfigurationError("RTL-Repo structurally exposes a verifier-only asset")
        records.append(
            {
                "task_id": spec.task_id,
                "context_count": len(items),
                "source_utf8_bytes": totals["source"],
                "generated_utf8_bytes": totals["generated"],
                "original_order_preserved": True,
                "verifier_only_target_not_materialized": True,
            }
        )
    return {
        "passed": bool(records),
        "model_calls": 0,
        "variant": variant,
        "suite_version": suite_version,
        "projection_version": projection_version,
        "completion_contract": completion_contract,
        "context_classification_rule": CONTEXT_CLASSIFICATION_RULE,
        "records": records,
    }


def _scoring_event_contract_qualification(
    definition: CampaignDefinition,
) -> dict[str, Any]:
    observation = canonical_tool_observation(
        "finish", {"accepted": True, "terminal": True}, is_error=False
    )
    stream = "\n".join(
        [
            json.dumps({"type": "turn.started", "model": "gpt-5.4"}, separators=(",", ":")),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "mcp_tool_call",
                        "server": "verigym",
                        "name": "finish",
                        "arguments": None,
                        "result": observation,
                    },
                },
                separators=(",", ":"),
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "model": "gpt-5.4",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
                separators=(",", ":"),
            ),
        ]
    )
    if validate_scoring_mcp_stream(stream) != ("finish",):
        raise ConfigurationError("AgentEval broker-validated scoring contract is unavailable")
    broker_attested = definition.agent_version_id in {
        _V9_AGENT_VERSION_ID,
        _CURRENT_AGENT_VERSION_ID,
    }
    direct_mcp_exposure = definition.agent_version_id == _CURRENT_AGENT_VERSION_ID
    return {
        "passed": True,
        "model_calls": 0,
        "contract": (
            "broker_sequence_attested_mcp_with_optional_final_message_v3"
            if broker_attested
            else "broker_validated_mcp_with_optional_final_message_v2"
        ),
        "transport_id_required_for_scoring": False,
        "transport_arguments_revalidated_by_event_projection": False,
        "broker_tool_sequence_required_for_scoring": broker_attested,
        "mcp_server_label_authoritative": not broker_attested,
        "direct_mcp_exposure_required": direct_mcp_exposure,
        "post_finish_assistant_message_present": False,
        "raw_event_stream_persisted": False,
        "agent_version_id": definition.agent_version_id,
        "official_references": list(_REFERENCE_URLS),
    }


def _frozen_run_configs(
    service: VeriGym,
    *,
    source_configs: dict[str, SuiteSourceConfig],
    docker_config: Any,
    runtime_descriptor: Any,
    prepared: dict[str, PreparedProfile],
    agent_options: dict[str, Any],
    output: Path,
    specs: tuple[CampaignRunSpec, ...],
) -> list[RunConfig]:
    configs: list[RunConfig] = []
    for spec in specs:
        profile_id = (
            prepared[spec.profile_name].profile.id if spec.profile_name is not None else None
        )
        base = RunConfig(
            task_id=spec.task_id,
            mode=InteractionMode.AGENT,
            agent="codex-cli-agenteval-agent",
            agent_options=agent_options,
            suite_source=source_configs[spec.source_key],
            runtime="docker",
            docker_config=docker_config,
            toolchain_profile=profile_id,
            agent_ppa_feedback=spec.ppa,
            agent_ppa_max_calls=3,
            seed=0,
            sample_index=0,
            output=output,
            run_id=spec.run_id,
        )
        configs.append(
            smoke._freeze_run_config(
                service,
                base,
                runtime_descriptor=runtime_descriptor,
                expected_profile=(
                    prepared[spec.profile_name].resolved if spec.profile_name is not None else None
                ),
            )
        )
    return configs


def _build_plan(
    definition: CampaignDefinition,
    *,
    capability: Any,
    auth: Any,
    runtime_descriptor: Any,
    prepared: dict[str, PreparedProfile],
    qualifications: dict[str, Any],
    configs: list[RunConfig],
    predecessor_path: Path,
) -> dict[str, Any]:
    if len(configs) != definition.process_count:
        raise ConfigurationError("campaign plan has the wrong frozen process count")
    plan = {
        "schema_version": "1.0",
        "campaign_id": definition.campaign_id,
        "campaign_kind": definition.key,
        "run_specs": _safe_specs(definition.specs),
        "model": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "seed": 0,
        "samples_per_task_profile": 1,
        "planned_codex_processes": definition.process_count,
        "automatic_retries": 0,
        "codex": {
            "version": capability.version_output,
            "executable_sha256": capability.executable_sha256,
            "capability_fingerprint": capability.capability_fingerprint,
            "agent_version_id": definition.agent_version_id,
            "agent_version_hash": definition.agent_version_hash,
            "prompt_hash": definition.prompt_hash,
            "tool_policy_fingerprint": definition.tool_policy_fingerprint,
            "auth": auth.safe_dict(),
        },
        "runtime": runtime_descriptor.model_dump(mode="json"),
        "profiles": {
            name: {
                "declared_hash": content_hash(item.profile),
                "resolved_hash": item.resolved.resolved_profile_hash,
                "component_hashes": resolved_profile_component_hashes(item.resolved),
            }
            for name, item in prepared.items()
        },
        "qualifications": qualifications,
        "run_config_hashes": [content_hash(item.identity_payload()) for item in configs],
        "predecessor_summary_hash": hash_bytes(predecessor_path.read_bytes()),
        "diagnostic_only": definition.diagnostic_only,
        "pilot_is_benchmark_score": False,
        "benchmark_score_claimed": False,
    }
    if definition.key.startswith("pilot-"):
        plan["sample_selection"] = {
            "verilog_eval_prior_task_ids_excluded": True,
            "rtl_repo_prior_task_ids_excluded": True,
            "rtl_repo_public_selection_window": "test-000006..test-000080",
            "rtl_repo_public_heuristic": "lowest_context_bytes_with_source_target_path",
            "rtllm_profile_pairs_reused": True,
            "rtllm_reuse_reason": "only previously qualified open and commercial PPA profiles",
        }
    return plan


def _safe_specs(specs: tuple[CampaignRunSpec, ...]) -> list[dict[str, Any]]:
    return [
        {
            "run_id": spec.run_id,
            "task_id": spec.task_id,
            "source_key": spec.source_key,
            "profile_name": spec.profile_name,
            "agent_ppa_feedback": spec.ppa,
        }
        for spec in specs
    ]


def _validate_predecessor(path: Path, definition: CampaignDefinition) -> dict[str, Any]:
    payload = path.read_bytes()
    try:
        summary = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("campaign predecessor is not valid JSON") from exc
    if not isinstance(summary, dict):
        raise ConfigurationError("campaign predecessor must be an object")
    runs = summary.get("runs")
    if definition.key == "qualification":
        expected = {
            "campaign_id": gymfix._CAMPAIGN_ID,
            "diagnostic_complete": True,
            "infrastructure_complete": True,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 6,
            "provider_observations_recorded": 6,
            "automatic_retries": 0,
        }
        required_ids = {
            "02-counter-dc",
            "04-rtl-repo-test-000003",
            "06-rtl-repo-test-000004-control",
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 6
        ):
            raise ConfigurationError(
                "qualification requires the complete read-only gym-fix receipt"
            )
        selected = {
            run.get("run_id"): run for run in runs if isinstance(run, dict) and run.get("run_id")
        }
        if set(selected).issuperset(required_ids) is False or any(
            selected[run_id].get("typed_finish") is not True
            or selected[run_id].get("provider_usage_complete") is not True
            or selected[run_id].get("timed_out") is True
            or selected[run_id].get("policy_failure") is True
            or selected[run_id].get("infrastructure_failure") is True
            for run_id in required_ids
        ):
            raise ConfigurationError("gym-fix receipt lacks the three event-fix control outcomes")
    elif definition.key == "qualification-v2":
        expected = {
            "campaign_id": _QUALIFICATION_ID,
            "qualification_complete": True,
            "infrastructure_complete": True,
            "fully_successful": False,
            "pilot_v2_authorized": False,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
        ):
            raise ConfigurationError(
                "qualification-v2 requires the immutable failed v6 qualification receipt"
            )
        selected = {
            run.get("run_id"): run for run in runs if isinstance(run, dict) and run.get("run_id")
        }
        expected_v6_runs = {
            "01-counter-dc": (True, True, None),
            "02-rtl-repo-test-000003": (
                False,
                True,
                "scoring_event_mcp_outside_verigym",
            ),
            "03-rtl-repo-test-000004": (False, False, "scoring_event_missing_finish"),
        }
        if set(selected) != set(expected_v6_runs) or any(
            selected[run_id].get("resolved") is not resolved
            or selected[run_id].get("typed_finish") is not typed_finish
            or selected[run_id].get("failure_subcategory") != subcategory
            or selected[run_id].get("provider_usage_complete") is not True
            or selected[run_id].get("identity_observation_count") != 1
            or selected[run_id].get("timed_out") is True
            or selected[run_id].get("policy_failure") is True
            or selected[run_id].get("infrastructure_failure") is True
            for run_id, (resolved, typed_finish, subcategory) in expected_v6_runs.items()
        ):
            raise ConfigurationError(
                "qualification-v2 predecessor differs from the frozen v6 outcomes"
            )
    elif definition.key == "qualification-v3":
        expected = {
            "campaign_id": _QUALIFICATION_V2_ID,
            "qualification_complete": False,
            "infrastructure_complete": False,
            "fully_successful": False,
            "pilot_v3_authorized": False,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
        ):
            raise ConfigurationError(
                "qualification-v3 requires the immutable failed v7 qualification receipt"
            )
        selected = {
            run.get("run_id"): run for run in runs if isinstance(run, dict) and run.get("run_id")
        }
        expected_v7_runs = {
            "01-counter-open": (True, True, True, False, None),
            "02-rtl-repo-test-000002": (
                False,
                False,
                True,
                False,
                "scoring_event_mcp_server",
            ),
            "03-rtl-repo-test-000005": (False, False, False, True, None),
        }
        if set(selected) != set(expected_v7_runs) or any(
            selected[run_id].get("resolved") is not resolved
            or selected[run_id].get("typed_finish") is not typed_finish
            or selected[run_id].get("provider_usage_complete") is not usage_complete
            or selected[run_id].get("timed_out") is not timed_out
            or selected[run_id].get("failure_subcategory") != subcategory
            or selected[run_id].get("identity_observation_count") != 1
            or selected[run_id].get("policy_failure") is True
            or selected[run_id].get("infrastructure_failure") is True
            for run_id, (
                resolved,
                typed_finish,
                usage_complete,
                timed_out,
                subcategory,
            ) in expected_v7_runs.items()
        ):
            raise ConfigurationError(
                "qualification-v3 predecessor differs from the frozen v7 outcomes"
            )
    elif definition.key == "qualification-v4":
        expected = {
            "campaign_id": _QUALIFICATION_V3_ID,
            "qualification_complete": True,
            "infrastructure_complete": True,
            "fully_successful": False,
            "pilot_v4_authorized": False,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
        ):
            raise ConfigurationError(
                "qualification-v4 requires the immutable failed v8 qualification receipt"
            )
        selected = {
            run.get("run_id"): run for run in runs if isinstance(run, dict) and run.get("run_id")
        }
        expected_v8_run_ids = {
            "01-counter-open",
            "02-rtl-repo-test-000003",
            "03-rtl-repo-test-000004",
        }
        if set(selected) != expected_v8_run_ids or any(
            selected[run_id].get("resolved") is not False
            or selected[run_id].get("typed_finish") is not True
            or selected[run_id].get("provider_usage_complete") is not True
            or selected[run_id].get("timed_out") is True
            or selected[run_id].get("failure_category") != "scoring_event_ineligible"
            or selected[run_id].get("failure_subcategory") != "scoring_event_mcp_server"
            or selected[run_id].get("identity_observation_count") != 1
            or selected[run_id].get("policy_failure") is True
            or selected[run_id].get("infrastructure_failure") is True
            for run_id in expected_v8_run_ids
        ):
            raise ConfigurationError(
                "qualification-v4 predecessor differs from the frozen v8 outcomes"
            )
    elif definition.key == "qualification-v5":
        expected = {
            "campaign_id": _QUALIFICATION_V4_ID,
            "qualification_complete": True,
            "infrastructure_complete": True,
            "fully_successful": False,
            "pilot_v5_authorized": False,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
        ):
            raise ConfigurationError(
                "qualification-v5 requires the immutable failed v9 qualification receipt"
            )
        selected = {
            run.get("run_id"): run for run in runs if isinstance(run, dict) and run.get("run_id")
        }
        expected_v9_runs = {
            "01-counter-open": (True, None),
            "02-rtl-repo-test-000003": (False, "scoring_event_mcp_tool"),
            "03-rtl-repo-test-000004": (False, "scoring_event_mcp_tool"),
        }
        if set(selected) != set(expected_v9_runs) or any(
            selected[run_id].get("resolved") is not resolved
            or selected[run_id].get("typed_finish") is not True
            or selected[run_id].get("provider_usage_complete") is not True
            or selected[run_id].get("timed_out") is True
            or selected[run_id].get("failure_subcategory") != subcategory
            or selected[run_id].get("identity_observation_count") != 1
            or selected[run_id].get("policy_failure") is True
            or selected[run_id].get("infrastructure_failure") is True
            for run_id, (resolved, subcategory) in expected_v9_runs.items()
        ):
            raise ConfigurationError(
                "qualification-v5 predecessor differs from the frozen v9 outcomes"
            )
    elif definition.key == "qualification-v6":
        expected = {
            "campaign_id": _QUALIFICATION_V5_ID,
            "qualification_complete": True,
            "infrastructure_complete": True,
            "fully_successful": False,
            "pilot_v6_authorized": False,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
        ):
            raise ConfigurationError(
                "qualification-v6 requires the immutable verifier-rejected v10 receipt"
            )
        selected = {
            run.get("run_id"): run for run in runs if isinstance(run, dict) and run.get("run_id")
        }
        expected_v10_runs = {
            "01-counter-open": True,
            "02-rtl-repo-test-000003": False,
            "03-rtl-repo-test-000004": True,
        }
        if set(selected) != set(expected_v10_runs) or any(
            selected[run_id].get("resolved") is not resolved
            or selected[run_id].get("typed_finish") is not True
            or selected[run_id].get("provider_usage_complete") is not True
            or selected[run_id].get("timed_out") is True
            or selected[run_id].get("failure_category") is not None
            or selected[run_id].get("failure_subcategory") is not None
            or selected[run_id].get("identity_observation_count") != 1
            or selected[run_id].get("policy_failure") is True
            or selected[run_id].get("infrastructure_failure") is True
            for run_id, resolved in expected_v10_runs.items()
        ):
            raise ConfigurationError(
                "qualification-v6 predecessor differs from the frozen v10 outcomes"
            )
        counter = selected["01-counter-open"]
        if (
            counter.get("compile_passed") is not True
            or counter.get("legal_candidate_ppa") is not True
            or counter.get("final_ppa_eligible") is not True
        ):
            raise ConfigurationError("qualification-v6 requires the healthy v10 PPA control")
    elif definition.key == "pilot-v2":
        expected = {
            "campaign_id": _QUALIFICATION_ID,
            "qualification_complete": True,
            "fully_successful": True,
            "pilot_v2_authorized": True,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
            or not all(
                isinstance(run, dict)
                and run.get("resolved") is True
                and run.get("typed_finish") is True
                and run.get("provider_usage_complete") is True
                and run.get("identity_observation_count") == 1
                for run in runs
            )
        ):
            raise ConfigurationError("pilot-v2 requires the fully successful v6 qualification")
    elif definition.key == "pilot-v3":
        expected = {
            "campaign_id": _QUALIFICATION_V2_ID,
            "qualification_complete": True,
            "fully_successful": True,
            "pilot_v3_authorized": True,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
            or not all(
                isinstance(run, dict)
                and run.get("resolved") is True
                and run.get("typed_finish") is True
                and run.get("provider_usage_complete") is True
                and run.get("identity_observation_count") == 1
                for run in runs
            )
        ):
            raise ConfigurationError("pilot-v3 requires the fully successful v7 qualification")
    elif definition.key == "pilot-v4":
        expected = {
            "campaign_id": _QUALIFICATION_V3_ID,
            "qualification_complete": True,
            "fully_successful": True,
            "pilot_v4_authorized": True,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
            or not all(
                isinstance(run, dict)
                and run.get("resolved") is True
                and run.get("typed_finish") is True
                and run.get("provider_usage_complete") is True
                and run.get("identity_observation_count") == 1
                for run in runs
            )
        ):
            raise ConfigurationError("pilot-v4 requires the fully successful v8 qualification")
    elif definition.key == "pilot-v5":
        expected = {
            "campaign_id": _QUALIFICATION_V4_ID,
            "qualification_complete": True,
            "fully_successful": True,
            "pilot_v5_authorized": True,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
            or not all(
                isinstance(run, dict)
                and run.get("resolved") is True
                and run.get("typed_finish") is True
                and run.get("provider_usage_complete") is True
                and run.get("identity_observation_count") == 1
                for run in runs
            )
        ):
            raise ConfigurationError("pilot-v5 requires the fully successful v9 qualification")
    elif definition.key == "pilot-v6":
        expected = {
            "campaign_id": _QUALIFICATION_V5_ID,
            "qualification_complete": True,
            "fully_successful": True,
            "pilot_v6_authorized": True,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
            or not all(
                isinstance(run, dict)
                and run.get("resolved") is True
                and run.get("typed_finish") is True
                and run.get("provider_usage_complete") is True
                and run.get("identity_observation_count") == 1
                for run in runs
            )
        ):
            raise ConfigurationError("pilot-v6 requires the fully successful v10 qualification")
    else:
        expected = {
            "campaign_id": _QUALIFICATION_V6_ID,
            "qualification_complete": True,
            "fully_successful": True,
            "pilot_v7_authorized": True,
            "diagnostic_only": True,
            "benchmark_score_claimed": False,
            "codex_processes_started": 3,
            "provider_observations_recorded": 3,
            "automatic_retries": 0,
        }
        if (
            definition.key != "pilot-v7"
            or any(summary.get(key) != value for key, value in expected.items())
            or not isinstance(runs, list)
            or len(runs) != 3
            or not all(
                isinstance(run, dict)
                and run.get("resolved") is True
                and run.get("typed_finish") is True
                and run.get("provider_usage_complete") is True
                and run.get("identity_observation_count") == 1
                for run in runs
            )
        ):
            raise ConfigurationError("pilot-v7 requires the fully successful v10/v3 qualification")
    return {
        "campaign_id": summary["campaign_id"],
        "summary_hash": hash_bytes(payload),
        "fully_successful": summary.get("fully_successful") is True,
        "read_only": True,
    }


def _execute_bounded(
    service: VeriGym,
    configs: list[RunConfig],
    output: Path,
    definition: CampaignDefinition,
) -> list[RunResult]:
    if len(configs) != definition.process_count:
        raise ConfigurationError("campaign launcher has the wrong frozen process count")
    ledger: list[dict[str, Any]] = []
    results: list[RunResult] = []
    for ordinal, config in enumerate(configs, start=1):
        record = {
            "ordinal": ordinal,
            "run_id": config.run_id,
            "task_id": config.task_id,
            "authorization_granted": True,
            "process_started": False,
            "provider_observation_recorded": False,
            "identity_observation_count": 0,
            "retry_count": 0,
            "status": "authorized",
        }
        ledger.append(record)
        pilot_v1._write_ledger(output, ledger)
        try:
            run = service.run(config)
        except Exception:
            run_dir = config.output.expanduser().resolve() / str(config.run_id)
            smoke._update_process_ledger_record(record, run_dir=run_dir)
            record["status"] = "infrastructure_failure"
            pilot_v1._write_ledger(output, ledger)
            raise
        smoke._update_process_ledger_record(record, run_dir=run.run_dir, run=run)
        record["identity_observation_count"] = len(run.manifest.external_agent_observations)
        record["provider_observation_recorded"] = _identity_observation_valid(run, definition)
        record["resolved"] = run.scorecard.resolved
        results.append(run)
        failure = run.scorecard.failure
        infrastructure = run.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        policy = failure is not None and failure.kind == "policy"
        identity_invalid = not record["provider_observation_recorded"]
        if infrastructure or identity_invalid:
            record["status"] = "infrastructure_failure"
        elif policy:
            record["status"] = "policy_failure"
        elif failure is not None:
            record["status"] = "contained_model_failure"
        elif not run.scorecard.resolved:
            record["status"] = "verifier_rejection"
        else:
            record["status"] = "completed"
        pilot_v1._write_ledger(output, ledger)
        if (infrastructure or identity_invalid or policy) and ordinal < len(configs):
            raise CampaignInfrastructureError(
                "campaign stopped after an infrastructure, identity, or safety-invalid run"
            )
    if len(results) != definition.process_count:
        raise ConfigurationError("campaign stopped before all frozen runs completed")
    return results


def _identity_observation_valid(result: RunResult, definition: CampaignDefinition) -> bool:
    observations = result.manifest.external_agent_observations
    identity_path = result.run_dir / "artifacts" / "codex_cli" / "identity.json"
    if len(observations) != 1 or not identity_path.is_file():
        return False
    observation = observations[0]
    return bool(
        observation.invocation_count == 1
        and observation.requested_model_id == "gpt-5.4"
        and observation.observed_model_id in {None, "gpt-5.4"}
        and observation.effective_reasoning_effort == "xhigh"
        and observation.harness_id == definition.agent_version_id
        and observation.agent_version_hash == definition.agent_version_hash
        and observation.prompt_contract_hash == definition.prompt_hash
        and observation.tool_policy_fingerprint == definition.tool_policy_fingerprint
    )


def _scan_outputs(
    results: list[RunResult],
    service: VeriGym,
    configs: dict[str, SuiteSourceConfig],
    profile_paths: dict[str, Path],
    inputs: dict[str, Path],
    specs: tuple[CampaignRunSpec, ...],
    *,
    site_paths: tuple[Path, ...] = (),
    bounded_event_categories_safe: bool = False,
) -> dict[str, Any]:
    sensitive: list[tuple[str, bytes]] = []
    seen_tasks: set[str] = set()
    for spec in specs:
        if spec.task_id in seen_tasks:
            continue
        seen_tasks.add(spec.task_id)
        suite, task, assets = service.load_task(spec.task_id, configs[spec.source_key])
        sensitive.extend(
            ("hidden_rtl", asset.content.encode())
            for asset in assets.hidden_assets
            if asset.content
        )
        reference = suite.reference_solution(task)
        if reference is not None:
            sensitive.extend(
                ("reference_rtl", value.encode()) for value in reference.files.values()
            )
    path_markers = [
        *(str(path).encode() for path in profile_paths.values()),
        *(str(path).encode() for path in inputs.values()),
        *(str(path).encode() for path in site_paths),
    ]
    findings: list[dict[str, str]] = []
    for result in results:
        for file in sorted(result.run_dir.rglob("*")):
            if file.is_symlink():
                findings.append({"run_id": result.manifest.run_id, "category": "symlink"})
                continue
            if not file.is_file() or file.stat().st_size > 16 * 1024 * 1024:
                continue
            relative = file.relative_to(result.run_dir).as_posix()
            payload = file.read_bytes()
            model_facing = relative.startswith("artifacts/codex_cli/")
            if not relative.startswith("candidate/"):
                for category, marker in sensitive:
                    scan_reference = category != "reference_rtl" or model_facing
                    if scan_reference and len(marker) >= 32 and marker in payload:
                        findings.append({"run_id": result.manifest.run_id, "category": category})
            for marker in path_markers:
                if model_facing and marker and marker in payload:
                    findings.append({"run_id": result.manifest.run_id, "category": "site_path"})
            commercial_scan_payload = payload
            if bounded_event_categories_safe:
                commercial_scan_payload = _without_safe_event_categories(payload)
            if model_facing and smoke._COMMERCIAL_DIAGNOSTIC.search(commercial_scan_payload):
                findings.append(
                    {"run_id": result.manifest.run_id, "category": "commercial_diagnostic"}
                )
    unique = [dict(item) for item in {tuple(sorted(item.items())) for item in findings}]
    return {"schema_version": "1.0", "passed": not unique, "findings": unique}


def _without_safe_event_categories(payload: bytes) -> bytes:
    """Remove frozen content-free enums before scanning for commercial diagnostics."""

    replacements = {
        b"scoring_event_mcp_server": b"",
        b"mcp_server_category_counts": b"transport_category_counts",
    }
    for marker, replacement in replacements.items():
        payload = payload.replace(marker, replacement)
    return payload


def _redaction_audit(results: list[RunResult], process_count: int) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for result in results:
        root = result.run_dir / "artifacts" / "codex_cli"
        process = _read_json(root / "process.json")
        summary = _read_json(root / "summary.json")
        broker = _read_json(root / "broker.json")
        forbidden = [
            name
            for name in ("raw_stdout.jsonl", "raw_stderr.txt", "training-transcript.json")
            if (root / name).exists() or (root / name).is_symlink()
        ]
        terminal_tool = broker.get("terminal_tool_name")
        terminal_path = broker.get("terminal_path_category")
        event_subcategory = summary.get("failure_subcategory")
        event_category_bounded = event_subcategory is None or (
            isinstance(event_subcategory, str)
            and (
                event_subcategory in _SCORING_EVENT_FAILURE_SUBCATEGORIES
                or event_subcategory == broker.get("policy_failure_subcategory")
                or event_subcategory == broker.get("infrastructure_failure_subcategory")
            )
        )
        passed = bool(
            not forbidden
            and process.get("raw_output_persisted") is False
            and process.get("message_content_persisted") is False
            and process.get("reasoning_content_persisted") is False
            and summary.get("training_transcript_captured") is False
            and summary.get("raw_event_stream_persisted") is False
            and (terminal_tool is None or terminal_tool in _TOOL_NAMES)
            and (terminal_path is None or terminal_path in _PATH_CATEGORIES)
            and event_category_bounded
        )
        records.append(
            {
                "run_id": result.manifest.run_id,
                "passed": passed,
                "forbidden_artifact_count": len(forbidden),
                "terminal_tool_sanitized": terminal_tool is None or terminal_tool in _TOOL_NAMES,
                "terminal_path_category_bounded": terminal_path is None
                or terminal_path in _PATH_CATEGORIES,
                "scoring_event_category_bounded": event_category_bounded,
            }
        )
    return {
        "schema_version": "1.0",
        "passed": len(records) == process_count and all(record["passed"] for record in records),
        "records": records,
    }


def _campaign_summary(
    results: list[RunResult],
    replay: dict[str, Any],
    scan: dict[str, Any],
    redaction: dict[str, Any],
    definition: CampaignDefinition,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for result in results:
        evidence_root = result.run_dir / "artifacts" / "codex_cli"
        broker = _read_json(evidence_root / "broker.json")
        process = _read_json(evidence_root / "process.json")
        usage = _read_json(evidence_root / "provider-usage.json")
        adapter_summary = _read_json(evidence_root / "summary.json")
        failure = result.scorecard.failure
        infrastructure_failure = result.scorecard.correctness.infrastructure_error or (
            failure is not None and failure.infrastructure
        )
        policy_failure = failure is not None and failure.kind == "policy"
        compile_passed = any(
            evaluation.test_id == "compile"
            and evaluation.passed
            and evaluation.candidate_hash == result.manifest.candidate_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        legal_candidate_ppa = any(
            evaluation.test_id == "ppa"
            and evaluation.passed
            and evaluation.metrics is not None
            and evaluation.candidate_hash == result.manifest.candidate_hash
            and evaluation.profile_hash == result.manifest.resolved_profile_hash
            for evaluation in result.manifest.agent_feedback_evaluations
        )
        ppa = result.scorecard.quality.ppa
        records.append(
            {
                "run_id": result.manifest.run_id,
                "task_id": result.manifest.task_id,
                "resolved": result.scorecard.resolved,
                "typed_finish": broker.get("finished") is True and broker.get("finish_calls") == 1,
                "identity_observation_count": len(result.manifest.external_agent_observations),
                "model_identity_valid": _identity_observation_valid(result, definition),
                "process_started": (evidence_root / "process.json").is_file(),
                "timed_out": process.get("timed_out") is True,
                "provider_usage_complete": usage.get("usage_complete") is True,
                "policy_failure": policy_failure,
                "infrastructure_failure": infrastructure_failure,
                "failure_category": failure.category if failure is not None else None,
                "failure_subcategory": (
                    failure.protocol_error_subcategory
                    if failure is not None and failure.protocol_error_subcategory is not None
                    else adapter_summary.get("failure_subcategory")
                ),
                "compile_passed": compile_passed,
                "legal_candidate_ppa": legal_candidate_ppa,
                "final_ppa_eligible": ppa is not None and ppa.eligible,
            }
        )
    ppa_records = [record for record in records if record["run_id"] in definition.ppa_run_ids]
    infrastructure_complete = bool(
        len(records) == definition.process_count
        and replay.get("all_valid") is True
        and scan.get("passed") is True
        and redaction.get("passed") is True
        and all(record["process_started"] for record in records)
        and all(record["model_identity_valid"] for record in records)
        and all(record["identity_observation_count"] == 1 for record in records)
        and not any(record["infrastructure_failure"] for record in records)
    )
    campaign_complete = bool(infrastructure_complete and len(records) == definition.process_count)
    fully_successful = bool(
        campaign_complete
        and all(record["resolved"] for record in records)
        and all(record["typed_finish"] for record in records)
        and all(record["provider_usage_complete"] for record in records)
        and not any(record["timed_out"] for record in records)
        and not any(record["policy_failure"] for record in records)
        and len(ppa_records) == len(definition.ppa_run_ids)
        and all(record["compile_passed"] for record in ppa_records)
        and all(record["legal_candidate_ppa"] for record in ppa_records)
        and all(record["final_ppa_eligible"] for record in ppa_records)
    )
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "campaign_id": definition.campaign_id,
        "campaign_kind": definition.key,
        "codex_processes_authorized": definition.process_count,
        "codex_processes_started": sum(record["process_started"] for record in records),
        "provider_observations_recorded": sum(record["model_identity_valid"] for record in records),
        "automatic_retries": 0,
        "runs": records,
        "all_candidates_resolved": len(records) == definition.process_count
        and all(record["resolved"] for record in records),
        "infrastructure_complete": infrastructure_complete,
        "fully_successful": fully_successful,
        "diagnostic_only": definition.diagnostic_only,
        "pilot_is_benchmark_score": False,
        "benchmark_score_claimed": False,
    }
    if definition.key == "qualification":
        summary["qualification_complete"] = campaign_complete
        summary["pilot_v2_authorized"] = fully_successful
    elif definition.key == "qualification-v2":
        summary["qualification_complete"] = campaign_complete
        summary["pilot_v3_authorized"] = fully_successful
    elif definition.key == "qualification-v3":
        summary["qualification_complete"] = campaign_complete
        summary["pilot_v4_authorized"] = fully_successful
    elif definition.key == "qualification-v4":
        summary["qualification_complete"] = campaign_complete
        summary["pilot_v5_authorized"] = fully_successful
    elif definition.key == "qualification-v5":
        summary["qualification_complete"] = campaign_complete
        summary["pilot_v6_authorized"] = fully_successful
    elif definition.key == "qualification-v6":
        summary["qualification_complete"] = campaign_complete
        summary["pilot_v7_authorized"] = fully_successful
    else:
        summary["pilot_complete"] = campaign_complete
    return summary


def _persist_final_evidence(
    output: Path,
    replay: dict[str, Any],
    scan: dict[str, Any],
    redaction: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    atomic_dump_json(output / "replay.json", replay)
    atomic_dump_json(output / "security-scan.json", scan)
    atomic_dump_json(output / "redaction-audit.json", redaction)
    atomic_dump_json(output / "summary.json", summary)


def _finalize_existing(arguments: argparse.Namespace, definition: CampaignDefinition) -> int:
    output = smoke._directory(arguments.output)
    site_work = smoke._directory(arguments.site_work)
    broker_root = smoke._directory(arguments.broker_root)
    inputs = pilot_v1._inputs(arguments)
    profile_paths = pilot_v1._profile_paths(arguments)
    predecessor_path = smoke._regular_file(arguments.predecessor_summary, "predecessor summary")
    predecessor = _validate_predecessor(predecessor_path, definition)
    plan = _read_json(smoke._regular_file(output / "plan.json", "campaign plan"))
    _validate_existing_plan(plan, definition)
    if plan.get("predecessor_summary_hash") != predecessor["summary_hash"]:
        raise ConfigurationError("campaign predecessor differs from the frozen plan")

    service = VeriGym(smoke._registries())
    source_configs = _source_configs(inputs, definition)
    _validate_sources(service, source_configs, definition.specs)
    _rtl_repo_v2_qualification(service, source_configs["rtl_repo"], definition.specs)
    results = _load_existing_results(output, definition)
    if plan["run_config_hashes"] != [result.manifest.run_config_hash for result in results]:
        raise ConfigurationError("campaign run configuration hashes differ from the plan")
    _validate_existing_ledger(output, results, definition)
    replay = smoke._offline_replay(results)
    scan = _scan_outputs(
        results,
        service,
        source_configs,
        profile_paths,
        inputs,
        definition.specs,
        site_paths=(site_work, broker_root, output, predecessor_path),
        bounded_event_categories_safe=definition.bounded_event_categories_safe,
    )
    redaction = _redaction_audit(results, definition.process_count)
    summary = _campaign_summary(results, replay, scan, redaction, definition)
    _persist_final_evidence(output, replay, scan, redaction, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["fully_successful"] else 2


def _validate_existing_plan(plan: Any, definition: CampaignDefinition) -> None:
    expected = {
        "campaign_id": definition.campaign_id,
        "campaign_kind": definition.key,
        "run_specs": _safe_specs(definition.specs),
        "model": "gpt-5.4",
        "reasoning_effort": "xhigh",
        "seed": 0,
        "samples_per_task_profile": 1,
        "planned_codex_processes": definition.process_count,
        "automatic_retries": 0,
        "diagnostic_only": definition.diagnostic_only,
        "pilot_is_benchmark_score": False,
        "benchmark_score_claimed": False,
    }
    if not isinstance(plan, dict) or any(plan.get(key) != value for key, value in expected.items()):
        raise ConfigurationError("existing plan differs from the frozen campaign definition")
    codex = plan.get("codex")
    expected_codex = {
        "agent_version_id": definition.agent_version_id,
        "agent_version_hash": definition.agent_version_hash,
        "prompt_hash": definition.prompt_hash,
        "tool_policy_fingerprint": definition.tool_policy_fingerprint,
    }
    hashes = plan.get("run_config_hashes")
    predecessor_hash = plan.get("predecessor_summary_hash")
    if (
        not isinstance(codex, dict)
        or any(codex.get(key) != value for key, value in expected_codex.items())
        or not isinstance(hashes, list)
        or len(hashes) != definition.process_count
        or not all(isinstance(item, str) and smoke._SHA256.fullmatch(item) for item in hashes)
        or not isinstance(predecessor_hash, str)
        or smoke._SHA256.fullmatch(predecessor_hash) is None
    ):
        raise ConfigurationError("existing campaign plan has invalid frozen identities")


def _load_existing_results(output: Path, definition: CampaignDefinition) -> list[RunResult]:
    runs_root = output / "runs"
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise ConfigurationError("existing campaign has no real runs directory")
    expected_ids = sorted(spec.run_id for spec in definition.specs)
    if sorted(entry.name for entry in runs_root.iterdir()) != expected_ids:
        raise ConfigurationError("existing campaign does not contain exactly its frozen runs")
    results: list[RunResult] = []
    for spec in definition.specs:
        run_dir = runs_root / spec.run_id
        if run_dir.is_symlink() or not run_dir.is_dir():
            raise ConfigurationError("existing campaign run directory is invalid")
        manifest = load_model(run_dir / "run_manifest.json", RunManifest)
        scorecard = load_model(run_dir / "scorecard.json", ScoreCard)
        if (
            manifest.run_id != spec.run_id
            or manifest.task_id != spec.task_id
            or scorecard.run_id != spec.run_id
            or scorecard.task_id != spec.task_id
        ):
            raise ConfigurationError("existing campaign run differs from its frozen slot")
        results.append(RunResult(run_dir=run_dir, manifest=manifest, scorecard=scorecard))
    return results


def _validate_existing_ledger(
    output: Path,
    results: list[RunResult],
    definition: CampaignDefinition,
) -> None:
    ledger = _read_json(
        smoke._regular_file(
            output / "evidence" / "process-authorizations.json",
            "campaign process authorization ledger",
        )
    )
    records = ledger.get("records")
    if not isinstance(records, list) or len(records) != definition.process_count:
        raise ConfigurationError("campaign ledger has the wrong record count")
    for ordinal, (record, result) in enumerate(zip(records, results, strict=True), start=1):
        expected = {
            "ordinal": ordinal,
            "run_id": result.manifest.run_id,
            "task_id": result.manifest.task_id,
            "authorization_granted": True,
            "process_started": (
                result.run_dir / "artifacts" / "codex_cli" / "process.json"
            ).is_file(),
            "provider_observation_recorded": _identity_observation_valid(result, definition),
            "identity_observation_count": len(result.manifest.external_agent_observations),
            "retry_count": 0,
        }
        if not isinstance(record, dict) or any(
            record.get(key) != value for key, value in expected.items()
        ):
            raise ConfigurationError("campaign ledger differs from run evidence")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("campaign evidence JSON is unavailable") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("campaign evidence JSON must be an object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
