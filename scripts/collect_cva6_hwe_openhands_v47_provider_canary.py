#!/usr/bin/env python3
"""Run the authorized two-task v47 atomic-shape-recovery provider canary once."""

from __future__ import annotations

import argparse
import copy
import importlib
import importlib.metadata
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Literal, cast

from verigym_openhands.hwe_agent import _validated_hwe_runtime_bridge
from verigym_openhands.hwe_command_runtime import build_hwe_command_runtime_config
from verigym_openhands.hwe_v19_canary_runtime import (
    OPENHANDS_V19_CANARY_API_KEY_ENV,
    OPENHANDS_V19_CANARY_BASE_URL_ENV,
    OPENHANDS_V19_CANARY_LITELLM_VERSION,
    OPENHANDS_V19_CANARY_MODEL,
    OPENHANDS_V19_CANARY_MODEL_IDENTITY,
    OPENHANDS_V19_CANARY_SDK_VERSION,
    OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
    OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
)
from verigym_openhands.hwe_v22 import (
    classify_v22_campaign_result,
    seal_v22_decision_receipt,
    seal_v22_trajectory_receipt,
)
from verigym_openhands.hwe_v22_protocol import OPENHANDS_V22_TOOL_CHOICE_POLICY
from verigym_openhands.hwe_v47_canary_runtime import (
    OPENHANDS_V47_CANARY_AGENT_VERSION_ID,
    OPENHANDS_V47_CANARY_CAMPAIGN_ID,
    OPENHANDS_V47_CANARY_CONTRACT_FORMAT,
    OPENHANDS_V47_CANARY_OPT_IN_ENV,
    OPENHANDS_V47_CANARY_SAMPLE_INDEX,
    OPENHANDS_V47_CANARY_SEED,
    OPENHANDS_V47_COMMAND_EXECUTION_BACKEND,
    OPENHANDS_V47_NUMPY_VERSION,
    OPENHANDS_V47_PILLOW_VERSION,
    build_v47_canary_agent_options,
    build_v47_canary_agent_version,
    validate_v47_canary_contract,
    validate_v47_canary_runtime_evidence,
)
from verigym_openhands.trajectory import (
    OpenHandsTrajectoryError,
    materialize_openhands_decisions,
    validate_openhands_training_trajectory,
)

from verigym.api import VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.external_agent import RuntimeExternalAgentBridge
from verigym.core.hashing import content_hash, hash_bytes, hash_directory
from verigym.core.security_scanner import require_security_scan_pass, scan_artifact_roots
from verigym.core.trace import TraceWriter
from verigym.core.workspace import WorkspacePolicy
from verigym.evolution.memory import validate_agent_version
from verigym.experiments.state import atomic_dump_json
from verigym.hwe.image_lock import HweCommandImageLock
from verigym.hwe.qwen_action_tokenizer import QwenDecisionExampleTokenizer
from verigym.runtimes.docker.runtime import DockerRuntime
from verigym.schemas.common import InteractionMode
from verigym.schemas.evolution import AgentVersionManifest
from verigym.schemas.external_agent import ExternalAgentAccounting
from verigym.schemas.run import RunConfig
from verigym.schemas.runtime import DockerRuntimeConfig, SessionSpec
from verigym.schemas.suite import SuiteSourceConfig

_collection = importlib.import_module(
    "scripts.collect_cva6_hwe_deepseek" if __package__ else "collect_cva6_hwe_deepseek"
)
_infrastructure_invalid = _collection._infrastructure_invalid
_load_tokenizer = _collection._load_tokenizer
_base_model_lock = _collection._base_model_lock

OPENHANDS_V47_APPROVAL_FORMAT = "verigym_openhands_hwe_v47_provider_canary_authorization_v1"
OPENHANDS_V47_REPORT_FORMAT = "verigym_openhands_hwe_v47_provider_canary_report_v1"
OPENHANDS_V47_IDENTITY = "openhands-hwe-v47-v22-provider-canary-v1"
OPENHANDS_V47_APPROVAL_HASH = "bdfb2e6a2f3e7e5ee465e011f73fa50c32f24d0c4d6fab76490b52326dbeab4a"

_V33_AUDIT_MERGE = "648fe717e88b36876245df09e73222f906f83918"
_V33_AUDIT_FILE_SHA256 = "63f814ebeee613e479db3c99f362211e6304778d11ab4cc35873c50f7750af5a"
_V33_TREE_HASH = "62963cb8d23d48ae31b328d27648fb693d263b698be526f4b7aa4e6df4aa02e6"
_V33_PROGRESS_HASH = "463aa8016d62e947421379cd925009c131a589d754e0c17e7c7f83c72fef26df"
_V33_PROGRESS_SHA256 = "267c8340e98b81a092216afccc5dadd0834960613920499c392f34522dd78839"
_V33_CATALOG_HASH = "05be424d40014e7ef69106f85e5ea161db2bb8e70103c8d1279e4a7c118f8e05"
_V33_CATALOG_SHA256 = "08c31fb7ad13d96fda850f114b34688ec22c0d96a865eb21e5d19fe03df5a423"

_V36_AUDIT_MERGE = "e650953f5d508c1b53dc35c325944108d4b90420"
_V36_AUDIT_FILE_SHA256 = "58cb19ce494248ff8714a9786563b6b70b818c8d49eed5e880f169467a436ddd"
_V36_ROOT_CAUSE_MERGE = "24705dff206845cb8741a7cadeeaeaa6913cc178"
_V36_ROOT_CAUSE_FILE_SHA256 = "8725ef62106101b741ba371db1c60e484814ed5d4867fd9a53841806e125b352"
_V36_TREE_HASH = "ccf9094dfe373587454346f5b52b4a8f7d3ade828b4f15b524c63d14a6d26f4d"
_V36_REPORT_HASH = "debf637e7697c921c24898a027a907d045514c0f7f65d131ad7e3471998124d0"
_V36_REPORT_SHA256 = "9abe705efe3ddfd24c51f9261febe5349a8649037771036063b803c8523e55e8"
_V36_AGENT_VERSION_HASH = "0f346efa5627469a7d71c595459e97b061225385d005d124816b91c8bc37ed77"
_V36_AGENT_VERSION_SHA256 = "43d212129f9c99c234ffe81b267a000274e299e9bba241ef77fe684cf8e8ed03"
_V36_CONTRACT_RECEIPT_HASH = "07d88c51512cc57f55d857627700d3fd8fbe0e87668eb355a4bbb45068365bd7"
_V36_CONTRACT_RECEIPT_SHA256 = "70bd0f9929a3cae3acd52cd12c9cb5602232773e46ea746e13f9eab9c71a2644"
_V36_PREFLIGHT_RECEIPT_HASH = "fb784dbcd80a369833634edc4ccf8b875d5393984c40eedc1260e2cc689c5e68"
_V36_PREFLIGHT_RECEIPT_SHA256 = "f5fae39b09cc20ca58f2b67a3e59e190738a1eb7a8ac7be6ad6390502a6b887b"
_V36_ATTEMPT_SHA256 = "fa0bc526bae7d7734bec3adca53ff57d8b1f67b3fc6a7072a25e85ca9575634f"

_V37_STOP_AUDIT_MERGE = "9f5e0153047c10eb1e799e98075af8d4ac6b73c8"
_V37_STOP_AUDIT_FILE_SHA256 = "f364e09eca02723e3ff5bdc6bf06459a793aaddb4b978a8858013caa274b73e1"
_V37_STOP_TREE_HASH = "796b2f56316c4b0b2fb0392b3ea8b218bc2f84030e9a79c30c0e46227d241ee9"
_V37_STOP_RECEIPT_HASH = "ef98bbdda2329fa0746c8c24c5fd51e614007a73347371654d0e86ebcc48377e"
_V37_STOP_RECEIPT_SHA256 = "2107843637320035bfa748e8d16e1a896495b7c1551223ebd9f939a037466521"

_V38_AUTHORIZATION_MERGE = "e2583dc1997700387f3c74f526fb6b2e6f6a84b5"
_V38_FAILURE_AUDIT_MERGE = "99df7a674784c428527222a73828024a248f5174"
_V38_FAILURE_AUDIT_FILE_SHA256 = "ca452885846f7aa942e06bbc003bc3d3666a6d60df52fa16250e142b6d96baa7"
_V38_TREE_HASH = "e5e9d518b7f0bf24a0b32947b5ea42efb3d15ac96f44943918bcafeaf171f890"
_V38_REPORT_HASH = "a90698e672c38c341735c130e1691e13370d44aa75a5b8bf298ec38e1dfb1e6a"
_V38_REPORT_SHA256 = "ab0ac6a6a5594a40dbcf722ba8d7f5a790789e7864ee7e4e3b4e41841367921b"
_V38_AGENT_VERSION_HASH = "05387b92124088c35763440e54e3a0513bf649aec4ad4233371a90e27771ac07"
_V38_AGENT_VERSION_SHA256 = "3707fa5fee7c062c5be4e0ae5fb8352849aee221275d4bdb1eca78934e085cec"
_V38_CONTRACT_RECEIPT_HASH = "380ef13bb6ca3282afb4f502ca572f5147758f489b5e5cb1000dc56a7716cb5e"
_V38_CONTRACT_RECEIPT_SHA256 = "de837d309b1096832578d2c0e7df62b702da6e1e3cde6a9ceabb7efd4358de6c"
_V38_PREFLIGHT_RECEIPT_HASH = "3117d560a71cdb146d4ae44144f0cc01f0bf778f045c1fbce1bd2f291dd25fd6"
_V38_PREFLIGHT_RECEIPT_SHA256 = "04224c4fd4e72eab4961525b6e6d5f86a63fcf2336e01b5fd2a1e7437141dc30"
_V38_ATTEMPT_SHA256 = "1b54b5f58e8317a5709acfdcd08f91da16ce9f5214caa9c8937a516205d0f754"
_V38_SECURITY_SCAN_HASH = "99bc36f5098e1e7f2dcf812cd1aaa5698b00e6d7748b34e938f0f8f933b64b05"
_V38_SECURITY_SCAN_SHA256 = "6e02973cb1c961fca48efb85d7fd8599c19f8735d359cd9b56767ce7999ecf84"

_V39_AUTHORIZATION_MERGE = "732d82f835e9c2ba9e0b681244e5edc1410c1484"
_V39_FAILURE_AUDIT_MERGE = "5a3c4cdb547cd3ca8bc7d3c45d21267e5d47648b"
_V39_FAILURE_AUDIT_FILE_SHA256 = "681d56d87627ededab88ac38ef51641e856016a62548132b35541d4ec434b263"
_V39_TREE_HASH = "1fee66ee5a9f3902ce726a4459da875ba2dccb13c576763c2a4b5d6b44bac6be"
_V39_REPORT_HASH = "072f237207f22f7f04a640819bded258d05e880ffc634340739e956064b03077"
_V39_REPORT_SHA256 = "3f9f65de1f5e585c58630d30e49d8576aefbefc6cbc33001396400d85b08acca"
_V39_AGENT_VERSION_HASH = "0f16474f7803326d726905a28e7e178ff0871f0093c64a514a90d0b8c59602f9"
_V39_AGENT_VERSION_SHA256 = "66d708d480e45a1abb51d851418c5e192ad36efa7d6e50a81fdc3d133c828a95"
_V39_CONTRACT_RECEIPT_HASH = "5cf8bd093be852361fe3019f7a2a23be08ebde5928cab545f27e03015506b29e"
_V39_CONTRACT_RECEIPT_SHA256 = "4accedc50bb29bbd115454fe0c9889f0f1757d9f84a8da0de4457470c6e978c0"
_V39_PREFLIGHT_RECEIPT_HASH = "789201e5ec09b21d1b3929f766f35b312dd2297b1bdbaaa2de2e58460d109c23"
_V39_PREFLIGHT_RECEIPT_SHA256 = "f94fae2197462cd870f8c52174b377fe15a38de8fca1de739a8d80aa5e878255"
_V39_ATTEMPT_SHA256 = "f4709f0cb1901fba17adfcdd05eb931ebd8f8d7685dd495efef8882ef384b7ff"
_V39_SECURITY_SCAN_HASH = "59a9e564dc07a0161f2216c23784c54532890ee6a085cb09efddc46abe8f5f7b"
_V39_SECURITY_SCAN_SHA256 = "83079b8de700a2c54e19b72ba186e70370253ef76de838794f34afa869f460a5"

_V41_AUTHORIZATION_MERGE = "b8c6651ef78bdaed37a63c7d0cd9b3f8f7b71cc7"
_V41_FAILURE_AUDIT_MERGE = "a2f756330a196da04c30788ce4381c6dffde6440"
_V41_FAILURE_AUDIT_FILE_SHA256 = "bda7d975d45cb3fb624cd90d993c26297c0f5264483a1d825ec9db395413ecb1"
_V41_MAIN_RUN_ID = 33478968324
_V41_TREE_HASH = "b105784e55d7024e1f17074d1779e652060780721c67bded3bd27707a4e195f7"
_V41_REPORT_HASH = "dabd954df613b624279da8d1a0600c024ecd344c759afdbb638a36aefb896922"
_V41_REPORT_SHA256 = "a4a774177b1a78d34057ae2d5223957a2d65456a601b9dee024d2f2964473a5c"
_V41_ATTEMPT_RUN_HASH = "24b643931cdb45cb6680bad8e37ca2685a00ef6be0744d2cad947bc92c2a65a7"
_V41_ATTEMPT_SHA256 = "d4640183529f47e9ffd7559b75d71c39639539de088a6e76fb5d6a781a8ee6d5"
_V41_AGENT_VERSION_HASH = "c7791deb031c3ff0623b70faf111e0287cc3cc1458a3353853f6bb3452bf6963"
_V41_AGENT_VERSION_SHA256 = "b2fefa5b060df24f1242c6e686dd4768071a692f138a18fa693571cde4daaeec"
_V41_CONTRACT_RECEIPT_HASH = "3019b501e9d8cede16624ccbf8f31080066fef2ef4bb0eff48638384c90ecdfa"
_V41_CONTRACT_RECEIPT_SHA256 = "f0f34d933169539a0be3368dd30cb2e9788db26cee2226a214f1f6bf442b714a"
_V41_PREFLIGHT_RECEIPT_HASH = "f9d98d51c29cd6f8ff761afbb1c2af10c4c0515addcb0d61595597fc921fb4eb"
_V41_PREFLIGHT_RECEIPT_SHA256 = "e93455543a454eff69907c2719052e3fecda292b9a079be6bd1d59fea85b70c4"
_V41_SECURITY_SCAN_HASH = "2658641431987039afbd4798e8e1d91d233a548bb2932915f0a0fe40c9313bbe"
_V41_SECURITY_SCAN_SHA256 = "9f17ba60ec4d9f85c1152686ce5cf87a5f431fffb95427282026dd2138af0065"

_V46_AUTHORIZATION_MERGE = "e56d4eed4e403985f6f1134a35acbd79a6bec5c9"
_V46_RESULT_AUDIT_MERGE = "3f823123a5bda5fe3c36db379697103341c68e3e"
_V46_RESULT_AUDIT_FILE_SHA256 = "222d7b9da15e6041549004b40eb6ccffc0435bb084c7fc76494611e727277736"
_V46_MAIN_RUN_ID = 33497174753
_V46_TREE_HASH = "80e224648c35fb8e40155a0428e57d29cf867a42be7438e3b04e67c9960d2a40"
_V46_PROGRESS_HASH = "dbf9b49e385b7b59819dd85748ed0990a0492cbc92d438a4c3aab448474f15ea"
_V46_PROGRESS_SHA256 = "e7833ea4495aae1ee2f5665bb713e8fb4d36e3d84656ed32d7174722f36750bf"
_V46_CATALOG_HASH = "94002a251b6a4036199c344d718c2668bbc2a3db64b0bffbac8367cf714590c9"
_V46_CATALOG_SHA256 = "97ae068650536b9654e0dc8a0c795759225bd7dbcc6a6982b46dd3c83fb7f003"
_V46_CONTRACT_HASH = "2423735c54cac89a9798afb353dfd700663586c031ba2af8366e875c68d1b8dc"
_V46_CONTRACT_SHA256 = "daa26401d58796ceae54b671dd679402bd7348b424c0c4c670349090357bfa17"

_V22_PROTOCOL_MERGE = "299cc6212be24f12c7cb695f596e4328258e294d"
_V22_PROTOCOL_AUDIT_SHA256 = "1328c6ddcdad557311832531844a3a827ed5fbb2d8412938c8a611862be21a62"
_V22_PROTOCOL_MAIN_RUN_ID = 33471695480

_BROKER_ROOT_ENV = "VERIGYM_OPENHANDS_BROKER_ROOT"
_MCP_PYTHONPATH_ENV = "VERIGYM_OPENHANDS_MCP_PYTHONPATH"
_BROKER_ROOT = "/data/jzhu484/Agent/.verigym-tmp/oh-v47"
_MCP_PYTHONPATH_ENTRIES = (
    "/data/jzhu484/Agent/VeriGym/src",
    "/data/jzhu484/Agent/VeriGym/integrations/verigym-hwe-bench/src",
    "/data/jzhu484/Agent/VeriGym/integrations/verigym-openhands/src",
    "/data/jzhu484/Agent/VeriGym/integrations/verigym-deepseek-harness/src",
)

_TRAINING_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2802"
_VALIDATION_TASK = "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3204"
_TASKS = (_TRAINING_TASK, _VALIDATION_TASK)
_LOCK_INPUTS = {
    _TRAINING_TASK: {
        "task_hash": "e9bfb9718e9fe66ef83494aac697baabda2ad4aad62d4c61735fdd33f3a62e30",
        "source_hash": "51d5b7c6cdb5cb064cee20f9bfea993594b7744ffaf679ca53505ec059129757",
        "file_sha256": "c544ad2fe377f06ce1df30263ade79631ccf0242e0ceb6a15cf7efebc9ad3e9d",
        "lock_hash": "56eb714597459b0f6462d78049fc85fef3cd68d52de90931fec7ed2bc9757bde",
        "security_scan_file_sha256": (
            "63478f7ad8438c576beaab9085d72898843cf4b9caa68e5afc88378928e13227"
        ),
        "security_scan_id": "523853d2ac78c030cc5ae47e8fea21ad1f526f8afa5d841e07ab1f833856c59c",
        "command_image": "sha256:f370d7c34c8ea2c7d7a2fdde6a5bc47bf5cf887f5f35ab4bd759bb18b173a4db",
        "verifier_image": "sha256:88246baf91e53c45f266ef078bf62939329197366b8ac077f36cbdc1f8e05cdb",
    },
    _VALIDATION_TASK: {
        "task_hash": "9322fa0b8455126e5c5f2e68ae02c47484935d5ea84bf69b9e6494658e229e86",
        "source_hash": "15861c5f52071656a4ac8dbe7f96df49c974d24c2e3f53f9e449eba12794f02f",
        "file_sha256": "a3a29f4ad2515c9502b3716e8644806154c7f9a74d388f9cd9c741d81458dc22",
        "lock_hash": "4e6bcb561d1c631955dcf9b4a2475a0b09d5bb6bb6b98441cd20101f893400d7",
        "security_scan_file_sha256": (
            "6357976446539e526c15cf22a8e9616df650e4ac30117934898b7a40eb339ed1"
        ),
        "security_scan_id": "55e94ec5fd12482534238867e109f920779685d0ef9f18b0db03e99f88be62cf",
        "command_image": "sha256:ed935e093a8f5df4f081ee94d7fb3696335350053dd74fbbd5178b23c2fd1784",
        "verifier_image": "sha256:459deab1a9b65a25be4583087238308dd12e773b818e720299cc8cafe55f4f64",
    },
}
_TRAINING_SOURCE_LOCK_SHA256 = "7d6b8ca1dd0ebcdf55963666432efbb505a01365f3f01ef8d407953f659b4c88"
_VALIDATION_SOURCE_LOCK_SHA256 = "ab23ac165898d66c54fc165de21e3eddfadc732542d5149ad15074c368447fa8"
_BASE_MODEL_LOCK_SHA256 = "fb91ef923333c0bb251ca20d09801ee66aedf4a693b3adb85bbfb60858d8368b"
_MODEL_SNAPSHOT_HASH = "fce78eefb5b60ff95c480d2fb823bb45370a4abc933d6114a84d6a321486b156"
_TOKENIZER_HASH = "440110a9c8523a13003af840f2b31ce90709383488fcc7a62cfc19ab8ead6c6e"
_MAX_JSON_BYTES = 64 * 1024 * 1024
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_openhands_v47_provider_canary_v1.json",
    "docs/audits/2026-09-01_openhands-v33-codex-free-materialization-passed.md",
    "docs/audits/2026-09-01_openhands-v36-provider-canary-failed-closed.md",
    "docs/audits/2026-09-01_openhands-v36-provider-response-root-cause.md",
    "docs/audits/2026-09-01_openhands-v37-provider-canary-stopped-before-output.md",
    "docs/audits/2026-09-01_openhands-v38-provider-canary-failed-closed.md",
    "docs/audits/2026-09-01_openhands-v39-provider-canary-failed-closed.md",
    "docs/audits/2026-09-01_openhands-v41-provider-canary-failed-closed.md",
    "docs/audits/2026-09-01_openhands-v46-pr2802-canary-materialization-result.md",
    "docs/audits/2026-09-01_openhands-v22-empty-content-normalization.md",
    "docs/audits/2026-09-01_openhands-v47-provider-canary-authorization.md",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_agent.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v22.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v22_protocol.py",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v47_canary_runtime.py",
    "scripts/collect_cva6_hwe_openhands_v47_provider_canary.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--v33-materialization-root", type=Path, required=True)
    parser.add_argument("--v46-materialization-root", type=Path, required=True)
    parser.add_argument("--failed-v36-canary-root", type=Path, required=True)
    parser.add_argument("--stopped-v37-canary-root", type=Path, required=True)
    parser.add_argument("--failed-v38-canary-root", type=Path, required=True)
    parser.add_argument("--failed-v39-canary-root", type=Path, required=True)
    parser.add_argument("--failed-v41-canary-root", type=Path, required=True)
    parser.add_argument("--training-source", type=Path, required=True)
    parser.add_argument("--validation-source", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--base-model-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign-id", default=OPENHANDS_V47_CANARY_CAMPAIGN_ID)
    return parser


def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute at most two fresh episodes and stop after the first failed plane."""

    authorization = _validated_authorization(_load_json(arguments.authorization))
    _require_opt_in(arguments.campaign_id)
    source_commit = _merged_source_commit()
    v33_materialization = _safe_directory(arguments.v33_materialization_root, "v33 materialization")
    v46_materialization = _safe_directory(arguments.v46_materialization_root, "v46 materialization")
    contract, catalog, progress, locks = _materialized_contract(
        v46_materialization, v33_materialization
    )
    failed_v36 = _failed_v36_evidence(
        _safe_directory(arguments.failed_v36_canary_root, "v36 failed canary")
    )
    stopped_v37 = _stopped_v37_evidence(
        _safe_directory(arguments.stopped_v37_canary_root, "v37 stopped canary")
    )
    failed_v38 = _failed_v38_evidence(
        _safe_directory(arguments.failed_v38_canary_root, "v38 failed canary")
    )
    failed_v39 = _failed_v39_evidence(
        _safe_directory(arguments.failed_v39_canary_root, "v39 failed canary")
    )
    failed_v41 = _failed_v41_evidence(
        _safe_directory(arguments.failed_v41_canary_root, "v41 failed canary")
    )
    control_plane = _control_plane_contract()
    if authorization["schedule"]["task_ids"] != list(_TASKS):
        raise ConfigurationError("OpenHands v47 authorization schedule changed")
    sources = {
        _TRAINING_TASK: _validated_source(
            arguments.training_source, expected_lock_sha256=_TRAINING_SOURCE_LOCK_SHA256
        ),
        _VALIDATION_TASK: _validated_source(
            arguments.validation_source, expected_lock_sha256=_VALIDATION_SOURCE_LOCK_SHA256
        ),
    }
    tokenizer_root = _safe_directory(arguments.tokenizer_root, "tokenizer")
    model_lock_path = _safe_file(arguments.base_model_lock)
    if hash_bytes(model_lock_path.read_bytes()) != _BASE_MODEL_LOCK_SHA256:
        raise ConfigurationError("OpenHands v47 base-model lock changed")
    model_lock = _base_model_lock(model_lock_path, tokenizer_root)
    if (
        model_lock["snapshot_hash"] != _MODEL_SNAPSHOT_HASH
        or model_lock["tokenizer_hash"] != _TOKENIZER_HASH
    ):
        raise ConfigurationError("OpenHands v47 Qwen tokenizer identity changed")
    tokenizer, transformers_version = _load_tokenizer(tokenizer_root)
    exact_tokenizer = QwenDecisionExampleTokenizer(tokenizer, tokenizer_root=tokenizer_root)
    if exact_tokenizer.tokenizer_hash != _TOKENIZER_HASH:
        raise ConfigurationError("OpenHands v47 exact tokenizer hash changed")

    agent_version = build_v47_canary_agent_version(
        contract=contract,
        source_commit=source_commit,
        command_image_locks=locks,
        failed_v39_report_hash=failed_v39["report_hash"],
        failed_v41_report_hash=failed_v41["report_hash"],
        v46_evidence_tree_hash=_V46_TREE_HASH,
        v46_catalog_hash=catalog["catalog_hash"],
        v46_contract_hash=_V46_CONTRACT_HASH,
        v22_protocol_audit_sha256=_V22_PROTOCOL_AUDIT_SHA256,
        control_plane_contract_hash=control_plane["contract_hash"],
    )
    for role in ("training", "validation"):
        build_v47_canary_agent_options(
            seed=OPENHANDS_V47_CANARY_SEED, role=role, agent_version=agent_version
        )
    root = _new_output(arguments.output)
    runs = root / "runs"
    scans = root / "security-scans"
    records = root / "trajectory-records"
    attempts_root = root / "attempts"
    for directory in (runs, scans, records, attempts_root):
        directory.mkdir(mode=0o700)
    atomic_dump_json(root / "agent-version.json", agent_version)
    atomic_dump_json(root / "contract-receipt.json", _contract_receipt(contract, locks))

    base_report: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V47_REPORT_FORMAT,
        "identity": OPENHANDS_V47_IDENTITY,
        "authorization_hash": authorization["authorization_hash"],
        "campaign_id": arguments.campaign_id,
        "status": "canary_running",
        "source_commit": source_commit,
        "v33_materialization_audit_merge_commit": _V33_AUDIT_MERGE,
        "v33_materialization_tree_hash": _V33_TREE_HASH,
        "v33_materialization_progress_hash": _V33_PROGRESS_HASH,
        "v33_command_image_catalog_hash": _V33_CATALOG_HASH,
        "failed_v36_audit_merge_commit": _V36_AUDIT_MERGE,
        "failed_v36_evidence_tree_hash": _V36_TREE_HASH,
        "failed_v36_report_hash": failed_v36["report_hash"],
        "v36_root_cause_merge_commit": _V36_ROOT_CAUSE_MERGE,
        "stopped_v37_audit_merge_commit": _V37_STOP_AUDIT_MERGE,
        "stopped_v37_evidence_tree_hash": _V37_STOP_TREE_HASH,
        "stopped_v37_receipt_hash": stopped_v37["receipt_hash"],
        "failed_v38_authorization_merge_commit": _V38_AUTHORIZATION_MERGE,
        "failed_v38_audit_merge_commit": _V38_FAILURE_AUDIT_MERGE,
        "failed_v38_evidence_tree_hash": _V38_TREE_HASH,
        "failed_v38_report_hash": failed_v38["report_hash"],
        "failed_v39_authorization_merge_commit": _V39_AUTHORIZATION_MERGE,
        "failed_v39_audit_merge_commit": _V39_FAILURE_AUDIT_MERGE,
        "failed_v39_evidence_tree_hash": _V39_TREE_HASH,
        "failed_v39_report_hash": failed_v39["report_hash"],
        "failed_v41_authorization_merge_commit": _V41_AUTHORIZATION_MERGE,
        "failed_v41_audit_merge_commit": _V41_FAILURE_AUDIT_MERGE,
        "failed_v41_evidence_tree_hash": _V41_TREE_HASH,
        "failed_v41_report_hash": failed_v41["report_hash"],
        "failed_v41_post_merge_main_run_id": _V41_MAIN_RUN_ID,
        "v46_authorization_merge_commit": _V46_AUTHORIZATION_MERGE,
        "v46_result_audit_merge_commit": _V46_RESULT_AUDIT_MERGE,
        "v46_evidence_tree_hash": _V46_TREE_HASH,
        "v46_materialization_progress_hash": progress["progress_hash"],
        "v46_command_image_catalog_hash": catalog["catalog_hash"],
        "v46_canary_contract_hash": _V46_CONTRACT_HASH,
        "v46_post_merge_main_run_id": _V46_MAIN_RUN_ID,
        "v22_protocol_merge_commit": _V22_PROTOCOL_MERGE,
        "v22_protocol_audit_sha256": _V22_PROTOCOL_AUDIT_SHA256,
        "v22_protocol_main_run_id": _V22_PROTOCOL_MAIN_RUN_ID,
        "control_plane_contract_hash": control_plane["contract_hash"],
        "canary_contract_hash": contract["contract_hash"],
        "schedule": copy.deepcopy(authorization["schedule"]),
        "runtime": copy.deepcopy(authorization["runtime"]),
        "model_transport_id": OPENHANDS_V19_CANARY_MODEL,
        "model_identity": OPENHANDS_V19_CANARY_MODEL_IDENTITY,
        "agent_version_id": OPENHANDS_V47_CANARY_AGENT_VERSION_ID,
        "agent_version_hash": agent_version.version_hash,
        "openhands_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
        "litellm_version": OPENHANDS_V19_CANARY_LITELLM_VERSION,
        "tiktoken_version": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
        "transformers_version": transformers_version,
        "numpy_version": OPENHANDS_V47_NUMPY_VERSION,
        "pillow_version": OPENHANDS_V47_PILLOW_VERSION,
        "base_model_lock_file_sha256": _BASE_MODEL_LOCK_SHA256,
        "base_model_snapshot_hash": model_lock["snapshot_hash"],
        "tokenizer_hash": exact_tokenizer.tokenizer_hash,
        "seed": OPENHANDS_V47_CANARY_SEED,
        "sample_index": OPENHANDS_V47_CANARY_SAMPLE_INDEX,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
        "attempts": [],
        "heldout_task_ids_loaded": [],
        "fallback_identity_created": False,
        "training_task_consumed_by_canary": True,
        "training_task_disposition": "pending_v47_result",
        "formal_training_schedule_requires_replacement": None,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
        "formal_collection_allowed": False,
    }
    _write_report(root, base_report)
    try:
        _zero_call_preflight(root, locks, sources)
    except Exception as exc:
        return _stop(
            root,
            base_report,
            [],
            status="stopped_infrastructure_invalid",
            reason=f"zero_call_preflight:{type(exc).__name__}",
        )

    service = _service()
    attempts: list[dict[str, Any]] = []
    for index, episode in enumerate(contract["schedule"]):
        task_id = str(episode["task_id"])
        role = str(episode["role"])
        episode_id = f"{role}-pr{task_id.rsplit('-', 1)[-1]}-s496-v47"
        try:
            attempt = _run_episode(
                service=service,
                contract=contract,
                episode=episode,
                episode_id=episode_id,
                source_root=sources[task_id],
                lock=locks[task_id],
                agent_version=agent_version,
                tokenizer=exact_tokenizer,
                runs=runs,
                scans=scans,
                records=records,
                root=root,
            )
        except Exception as exc:
            return _stop(
                root,
                base_report,
                attempts,
                status="stopped_infrastructure_or_security_invalid",
                reason=f"{episode_id}:{type(exc).__name__}",
            )
        attempts.append(attempt)
        atomic_dump_json(attempts_root / f"{episode_id}.json", attempt)
        _write_report(root, {**base_report, "attempts": attempts})
        stop_kind = _attempt_stop_kind(attempt)
        if stop_kind == "infrastructure_or_security_invalid":
            return _stop(
                root,
                base_report,
                attempts,
                status="stopped_infrastructure_or_security_invalid",
                reason=f"{episode_id}:invalid_result_plane",
            )
        if stop_kind == "six_plane_gate_failed":
            return _stop(
                root,
                base_report,
                attempts,
                status="canary_failed_closed",
                reason=f"{episode_id}:six_plane_gate_failed",
            )
        if index == 0 and task_id != _TRAINING_TASK:
            raise ConfigurationError("OpenHands v47 training canary schedule drifted")

    passed = len(attempts) == 2 and all(_attempt_stop_kind(item) is None for item in attempts)
    final = _seal_report(
        {
            **base_report,
            "status": (
                "canary_passed_formal_collection_allowed" if passed else "canary_failed_closed"
            ),
            "attempts": attempts,
            "canary_passed": passed,
            "canary_trajectory_count": sum(
                int(item.get("trajectory_receipt") is not None) for item in attempts
            ),
            "exact_64k_trajectory_count": sum(
                int(item.get("token_receipt") is not None) for item in attempts
            ),
            "formal_collection_allowed": passed,
            "training_task_disposition": (
                "import_canary_without_formal_reexecution"
                if passed
                else "replace_after_failed_canary"
            ),
            "formal_training_schedule_requires_replacement": not passed,
            **_observed_provider_accounting(root, attempts),
            "failure_reason": None if passed else "six_plane_gate_failed",
        }
    )
    atomic_dump_json(root / "canary-progress.json", final)
    atomic_dump_json(root / "canary-report.json", final)
    return final


def _run_episode(
    *,
    service: VeriGym,
    contract: dict[str, Any],
    episode: dict[str, Any],
    episode_id: str,
    source_root: Path,
    lock: HweCommandImageLock,
    agent_version: AgentVersionManifest,
    tokenizer: QwenDecisionExampleTokenizer,
    runs: Path,
    scans: Path,
    records: Path,
    root: Path,
) -> dict[str, Any]:
    task_id = str(episode["task_id"])
    role_value = episode["role"]
    if role_value not in {"training", "validation"}:
        raise ConfigurationError("OpenHands v47 episode role changed")
    role = cast(Literal["training", "validation"], role_value)
    source = SuiteSourceConfig(source_root=source_root, variant="repo-repair-v1")
    suite, task, _assets = service.load_task(task_id, source)
    snapshot = suite.source_snapshot()
    binding = contract["task_bindings"][task_id]
    if (
        snapshot is None
        or content_hash(task) != binding["task_hash"]
        or task.source.content_hash != binding["source_hash"]
    ):
        raise ConfigurationError("OpenHands v47 loaded task/source binding changed")
    started = time.monotonic()
    result = service.run(
        RunConfig(
            task_id=task_id,
            suite_source=source,
            expected_suite_source_snapshot=snapshot,
            expected_task_hash=binding["task_hash"],
            expected_source_hash=binding["source_hash"],
            mode=InteractionMode.AGENT,
            agent="openhands-hwe-agent",
            agent_options=build_v47_canary_agent_options(
                seed=int(episode["seed"]), role=role, agent_version=agent_version
            ),
            runtime="docker",
            docker_config=_runtime_config(lock),
            seed=int(episode["seed"]),
            sample_index=int(episode["sample_index"]),
            output=runs,
            run_id=episode_id,
            experiment_id=OPENHANDS_V47_CANARY_CAMPAIGN_ID,
            plan_item_id=episode_id,
            system_id=OPENHANDS_V47_CANARY_AGENT_VERSION_ID,
            base_seed=int(episode["seed"]),
        )
    )
    scorecard = result.scorecard.model_dump(mode="json")
    infrastructure_valid = not _infrastructure_invalid(result.scorecard)
    run_directory = Path(result.run_dir).resolve(strict=True)
    if not run_directory.is_relative_to(runs) or run_directory.is_symlink():
        raise ConfigurationError("OpenHands v47 run directory escaped its output root")
    evidence = run_directory / "artifacts" / "openhands_sdk"
    if not infrastructure_valid:
        campaign_result = classify_v22_campaign_result(
            scorecard,
            agent_protocol_valid=False,
            trajectory_eligible=False,
            infrastructure_valid=False,
            security_valid=False,
            admit_to_sft=False,
        )
        return _attempt(
            episode=episode,
            episode_id=episode_id,
            scorecard=scorecard,
            campaign_result=campaign_result,
            wall_seconds=time.monotonic() - started,
        )
    _validate_runtime_manifest(result.manifest.environment_summary, lock)

    protocol: dict[str, Any] | None = None
    agent_protocol_valid = False
    try:
        accounting = ExternalAgentAccounting.model_validate(
            _load_json(evidence / "accounting.json")
        )
        protocol = validate_v47_canary_runtime_evidence(
            broker=_load_json(evidence / "broker.json"),
            summary=_load_json(evidence / "summary.json"),
            accounting=accounting,
            protocol_receipt=_load_json(evidence / "v22-protocol-receipt.json"),
        )
        agent_protocol_valid = True
    except (KeyError, OSError, ValueError, ConfigurationError):
        pass

    trajectory: dict[str, Any] | None = None
    decision_records: list[dict[str, Any]] = []
    trajectory_eligible = False
    if agent_protocol_valid:
        try:
            trajectory = validate_openhands_training_trajectory(
                _load_json(evidence / "training-trajectory.json")
            )
            reproducibility = scorecard.get("reproducibility")
            if (
                trajectory["task_id"] != task_id
                or trajectory["verifier_resolved"] is not True
                or trajectory["sft_eligible"] is not True
                or not isinstance(reproducibility, dict)
            ):
                raise OpenHandsTrajectoryError("OpenHands v47 trajectory binding changed")
            decision_records = materialize_openhands_decisions(
                trajectory,
                binding={
                    "sample_id": content_hash(
                        {
                            "contract_hash": contract["contract_hash"],
                            "campaign_id": OPENHANDS_V47_CANARY_CAMPAIGN_ID,
                            "episode_id": episode_id,
                            "scorecard_hash": content_hash(scorecard),
                        }
                    ),
                    "task_hash": binding["task_hash"],
                    "source_hash": binding["source_hash"],
                    "candidate_hash": reproducibility["candidate_hash"],
                    "verifier_hash": reproducibility["verifier_hash"],
                },
                tokenizer=tokenizer,
            )
            trajectory_eligible = bool(decision_records)
        except (KeyError, OSError, ValueError, ConfigurationError, OpenHandsTrajectoryError):
            trajectory = None
            decision_records = []

    record_dir: Path | None = None
    record_path: Path | None = None
    if trajectory_eligible:
        record_dir = records / episode_id
        record_dir.mkdir(mode=0o700)
        record_path = record_dir / "decisions.jsonl"
        _atomic_jsonl(record_path, decision_records)
    scan_roots = [evidence]
    private_audit = run_directory / "private-audit"
    if private_audit.is_dir() and not private_audit.is_symlink():
        scan_roots.append(private_audit)
    if record_dir is not None:
        scan_roots.append(record_dir)
    security_report = scan_artifact_roots(
        scan_roots,
        report_id=f"openhands-hwe-v47-{episode_id}",
        proxy_values=_provider_values(),
        forbidden_host_roots=(str(source_root), str(Path.cwd().resolve())),
    )
    atomic_dump_json(scans / f"{episode_id}.json", security_report)
    security_valid = security_report.gate == "pass"
    if security_valid:
        require_security_scan_pass(security_report)
    try:
        provider_value_scan = _scan_provider_values(root)
    except ConfigurationError:
        security_valid = False
        provider_value_scan = {
            "passed": False,
            "provider_value_count_scanned": 2,
            "provider_value_hit_count": None,
            "provider_values_persisted_or_hashed": None,
        }

    campaign_result = classify_v22_campaign_result(
        scorecard,
        agent_protocol_valid=agent_protocol_valid,
        trajectory_eligible=trajectory_eligible,
        infrastructure_valid=infrastructure_valid,
        security_valid=security_valid,
        admit_to_sft=trajectory_eligible,
    )
    trajectory_receipt: dict[str, Any] | None = None
    decision_receipt: dict[str, Any] | None = None
    token_receipt: dict[str, Any] | None = None
    if campaign_result["sft_admitted"] is True:
        assert protocol is not None and trajectory is not None and record_dir is not None
        trajectory_receipt = seal_v22_trajectory_receipt(
            trajectory=trajectory,
            protocol_receipt=protocol,
            campaign_result=campaign_result,
        )
        decision_receipt = seal_v22_decision_receipt(
            records=decision_records,
            trajectory_receipt=trajectory_receipt,
        )
        token_base = {
            "schema_version": "1.0",
            "format_id": "verigym_openhands_hwe_v47_exact_64k_token_receipt_v1",
            "episode_id": episode_id,
            "transcript_hash": trajectory["transcript_hash"],
            "decision_receipt_hash": decision_receipt["receipt_hash"],
            "decision_record_count": len(decision_records),
            "maximum_token_count": max(int(item["token_count"]) for item in decision_records),
            "max_length": 65_536,
            "truncation": "error",
            "truncation_applied": False,
            "decision_only_loss_mask": True,
            "public_tool_thought_supervised": True,
            "synthetic_shape_recovery_assistant_supervised": False,
        }
        token_receipt = {**token_base, "receipt_hash": content_hash(token_base)}
        atomic_dump_json(record_dir / "trajectory-receipt.json", trajectory_receipt)
        atomic_dump_json(record_dir / "decision-receipt.json", decision_receipt)
        atomic_dump_json(record_dir / "token-receipt.json", token_receipt)
        provider_value_scan = _scan_provider_values(root)

    return {
        "episode_id": episode_id,
        "role": role,
        "task_id": task_id,
        "seed": episode["seed"],
        "sample_index": episode["sample_index"],
        "run_id": episode_id,
        "run_hash": content_hash({"run_id": episode_id, "scorecard": scorecard}),
        "wall_seconds": time.monotonic() - started,
        "result": campaign_result,
        "runtime_command_image": lock.derived_command_image_id,
        "command_execution_backend": OPENHANDS_V47_COMMAND_EXECUTION_BACKEND,
        "security_scan_hash": security_report.report_hash,
        "provider_value_scan": provider_value_scan,
        "protocol_receipt": protocol,
        "trajectory_receipt": trajectory_receipt,
        "decision_receipt": decision_receipt,
        "token_receipt": token_receipt,
        "trajectory_file_sha256": (
            hash_bytes((evidence / "training-trajectory.json").read_bytes())
            if trajectory is not None
            else None
        ),
        "decision_records_file": (
            record_path.relative_to(root).as_posix() if record_path is not None else None
        ),
        "decision_records_file_sha256": (
            hash_bytes(record_path.read_bytes()) if record_path is not None else None
        ),
        "decision_record_count": len(decision_records) if trajectory_receipt is not None else 0,
        "maximum_decision_tokens": (
            max(int(item["token_count"]) for item in decision_records)
            if trajectory_receipt is not None
            else None
        ),
        "exact_64k_eligible": token_receipt is not None,
        "decision_only_loss_mask": token_receipt is not None,
        "public_tool_thought_supervised": token_receipt is not None,
        "synthetic_shape_recovery_assistant_supervised": False,
        "truncation_applied": False,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }


def _attempt(
    *,
    episode: dict[str, Any],
    episode_id: str,
    scorecard: dict[str, Any],
    campaign_result: dict[str, Any],
    wall_seconds: float,
) -> dict[str, Any]:
    return {
        "episode_id": episode_id,
        "role": episode["role"],
        "task_id": episode["task_id"],
        "seed": episode["seed"],
        "sample_index": episode["sample_index"],
        "run_id": episode_id,
        "run_hash": content_hash({"run_id": episode_id, "scorecard": scorecard}),
        "wall_seconds": wall_seconds,
        "result": campaign_result,
        "runtime_command_image": None,
        "command_execution_backend": OPENHANDS_V47_COMMAND_EXECUTION_BACKEND,
        "security_scan_hash": None,
        "provider_value_scan": None,
        "protocol_receipt": None,
        "trajectory_receipt": None,
        "decision_receipt": None,
        "token_receipt": None,
        "trajectory_file_sha256": None,
        "decision_records_file": None,
        "decision_records_file_sha256": None,
        "decision_record_count": 0,
        "maximum_decision_tokens": None,
        "exact_64k_eligible": False,
        "decision_only_loss_mask": False,
        "public_tool_thought_supervised": False,
        "synthetic_shape_recovery_assistant_supervised": False,
        "truncation_applied": False,
        "whole_episode_retries": 0,
        "provider_request_retries": 0,
    }


def _attempt_stop_kind(attempt: dict[str, Any]) -> str | None:
    result = attempt.get("result")
    if not isinstance(result, dict):
        raise ConfigurationError("OpenHands v47 attempt lacks its six-plane result")
    if result.get("infrastructure_valid") is not True or result.get("security_valid") is not True:
        return "infrastructure_or_security_invalid"
    if any(
        result.get(plane) is not True
        for plane in (
            "benchmark_verifier_pass",
            "agent_protocol_valid",
            "trajectory_eligible",
            "infrastructure_valid",
            "security_valid",
            "sft_admitted",
        )
    ):
        return "six_plane_gate_failed"
    if (
        attempt.get("exact_64k_eligible") is not True
        or attempt.get("decision_only_loss_mask") is not True
        or attempt.get("public_tool_thought_supervised") is not True
        or attempt.get("truncation_applied") is not False
        or not isinstance(attempt.get("trajectory_receipt"), dict)
        or not isinstance(attempt.get("decision_receipt"), dict)
        or not isinstance(attempt.get("token_receipt"), dict)
    ):
        return "six_plane_gate_failed"
    return None


def _materialized_contract(
    v46_root: Path,
    v33_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, HweCommandImageLock]]:
    if hash_directory(v46_root) != _V46_TREE_HASH:
        raise ConfigurationError("OpenHands v47 v46 evidence inventory changed")
    if hash_directory(v33_root) != _V33_TREE_HASH:
        raise ConfigurationError("OpenHands v47 v33 validation evidence inventory changed")
    progress_path = v46_root / "materialization-progress.json"
    catalog_path = v46_root / "canary-command-image-catalog.json"
    predecessor_contract_path = v46_root / "canary-contract.json"
    for path, expected in (
        (progress_path, _V46_PROGRESS_SHA256),
        (catalog_path, _V46_CATALOG_SHA256),
        (predecessor_contract_path, _V46_CONTRACT_SHA256),
    ):
        if hash_bytes(_safe_file(path).read_bytes()) != expected:
            raise ConfigurationError("OpenHands v47 v46 evidence file changed")
    progress = _validated_content_hash(_load_json(progress_path), "progress_hash")
    catalog = _validated_content_hash(_load_json(catalog_path), "catalog_hash")
    predecessor_contract = _validated_content_hash(
        _load_json(predecessor_contract_path), "contract_hash"
    )
    tasks = catalog.get("tasks")
    expected_schedule = [
        {
            "task_id": _TRAINING_TASK,
            "role": "training",
            "seed": OPENHANDS_V47_CANARY_SEED,
            "sample_index": OPENHANDS_V47_CANARY_SAMPLE_INDEX,
        },
        {
            "task_id": _VALIDATION_TASK,
            "role": "validation",
            "seed": OPENHANDS_V47_CANARY_SEED,
            "sample_index": OPENHANDS_V47_CANARY_SAMPLE_INDEX,
        },
    ]
    if (
        progress.get("status") != "completed_v22_canary_contract_materialized"
        or progress.get("progress_hash") != _V46_PROGRESS_HASH
        or progress.get("provider_calls") != 0
        or progress.get("provider_episodes") != 0
        or progress.get("model_process_count") != 0
        or progress.get("canary_executed") is not False
        or progress.get("collection_started") is not False
        or progress.get("formal_collection_allowed") is not False
        or progress.get("formal_collection_started") is not False
        or progress.get("training_started") is not False
        or progress.get("production_training_ready") is not False
        or progress.get("heldout_task_ids_loaded") != []
        or catalog.get("catalog_hash") != _V46_CATALOG_HASH
        or catalog.get("task_count") != 2
        or catalog.get("provider_credentials_present") is not False
        or catalog.get("codex_present") is not False
        or catalog.get("runtime_network") != "none"
        or catalog.get("command_execution_backend") != OPENHANDS_V47_COMMAND_EXECUTION_BACKEND
        or not isinstance(tasks, list)
        or len(tasks) != 2
        or predecessor_contract.get("contract_hash") != _V46_CONTRACT_HASH
        or predecessor_contract.get("protocol_profile") != OPENHANDS_V22_TOOL_CHOICE_POLICY
        or predecessor_contract.get("schedule") != expected_schedule
        or predecessor_contract.get("provider_calls_during_materialization") != 0
        or predecessor_contract.get("formal_collection_allowed") is not False
        or predecessor_contract.get("formal_collection_started") is not False
        or predecessor_contract.get("training_started") is not False
        or predecessor_contract.get("production_training_ready") is not False
        or predecessor_contract.get("heldout_task_ids_loaded") != []
    ):
        raise ConfigurationError("OpenHands v47 v46 evidence state changed")
    catalog_tasks = {str(item.get("task_id")): item for item in tasks if isinstance(item, dict)}
    predecessor_bindings = predecessor_contract.get("task_bindings")
    if len(catalog_tasks) != 2 or not isinstance(predecessor_bindings, dict):
        raise ConfigurationError("OpenHands v47 v46 catalog inventory changed")

    locks: dict[str, HweCommandImageLock] = {}
    bindings: dict[str, dict[str, Any]] = {}
    for task_id in _TASKS:
        suffix = task_id.rsplit("-", 1)[-1]
        expected_input = _LOCK_INPUTS[task_id]
        evidence_root = v46_root if task_id == _TRAINING_TASK else v33_root
        lock_path = evidence_root / "image-locks" / f"pr-{suffix}.json"
        scan_path = evidence_root / "security-scans" / f"pr-{suffix}.json"
        if (
            hash_bytes(_safe_file(lock_path).read_bytes()) != expected_input["file_sha256"]
            or hash_bytes(_safe_file(scan_path).read_bytes())
            != expected_input["security_scan_file_sha256"]
        ):
            raise ConfigurationError("OpenHands v47 command-image evidence file changed")
        lock = HweCommandImageLock.model_validate(_load_json(lock_path))
        scan = _validated_content_hash(_load_json(scan_path), "security_scan_id")
        catalog_entry = catalog_tasks.get(task_id)
        predecessor_binding = predecessor_bindings.get(task_id)
        binding = {
            "task_hash": expected_input["task_hash"],
            "source_hash": expected_input["source_hash"],
            "command_image_lock_hash": expected_input["lock_hash"],
            "command_image": expected_input["command_image"],
            "verifier_image": expected_input["verifier_image"],
            "security_scan_id": expected_input["security_scan_id"],
        }
        if (
            not isinstance(catalog_entry, dict)
            or any(catalog_entry.get(key) != value for key, value in binding.items())
            or predecessor_binding != binding
            or catalog_entry.get("command_image_lock_file_sha256") != expected_input["file_sha256"]
            or lock.task_id != task_id
            or lock.task_hash != expected_input["task_hash"]
            or lock.source_hash != expected_input["source_hash"]
            or lock.lock_hash != expected_input["lock_hash"]
            or lock.derived_command_image_id != expected_input["command_image"]
            or lock.verifier_base_image_id != expected_input["verifier_image"]
            or lock.security_scan_id != expected_input["security_scan_id"]
            or scan.get("security_scan_id") != lock.security_scan_id
            or scan.get("scan_passed") is not True
            or scan.get("secrets_detected") is not False
            or lock.security_scan_passed is not True
            or lock.codex_present is not False
            or lock.provider_credentials_present is not False
            or lock.hidden_assets_present is not False
            or lock.reference_patch_present is not False
            or lock.verifier_payload_present is not False
            or lock.runtime_network != "none"
            or OPENHANDS_V47_COMMAND_EXECUTION_BACKEND not in lock.supported_execution_backends
        ):
            raise ConfigurationError("OpenHands v47 v46 command-image binding changed")
        locks[task_id] = lock
        bindings[task_id] = binding

    base = {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V47_CANARY_CONTRACT_FORMAT,
        "protocol_profile": OPENHANDS_V22_TOOL_CHOICE_POLICY,
        "predecessor_catalog_hash": catalog["catalog_hash"],
        "schedule": expected_schedule,
        "task_bindings": bindings,
        "runtime": {
            "command_execution_backend": OPENHANDS_V47_COMMAND_EXECUTION_BACKEND,
            "command_role": "credential_free_command_image",
            "network": "none",
            "codex_present": False,
            "provider_credentials_in_command_container": False,
        },
        "heldout_task_ids_loaded": [],
    }
    contract = validate_v47_canary_contract({**base, "contract_hash": content_hash(base)})
    return contract, catalog, progress, locks


def _failed_v36_evidence(root: Path) -> dict[str, Any]:
    if hash_directory(root) != _V36_TREE_HASH:
        raise ConfigurationError("OpenHands v47 v36 evidence inventory changed")
    paths = {
        "report": root / "canary-report.json",
        "progress": root / "canary-progress.json",
        "agent": root / "agent-version.json",
        "contract": root / "contract-receipt.json",
        "preflight": root / "zero-call-preflight.json",
        "attempt": root / "attempts" / "training-pr2330-s489-v36.json",
    }
    expected_file_hashes = {
        "report": _V36_REPORT_SHA256,
        "progress": _V36_REPORT_SHA256,
        "agent": _V36_AGENT_VERSION_SHA256,
        "contract": _V36_CONTRACT_RECEIPT_SHA256,
        "preflight": _V36_PREFLIGHT_RECEIPT_SHA256,
        "attempt": _V36_ATTEMPT_SHA256,
    }
    for name, path in paths.items():
        if hash_bytes(_safe_file(path).read_bytes()) != expected_file_hashes[name]:
            raise ConfigurationError("OpenHands v47 v36 evidence file changed")
    report = _validated_content_hash(_load_json(paths["report"]), "report_hash")
    progress = _validated_content_hash(_load_json(paths["progress"]), "report_hash")
    agent = validate_agent_version(
        AgentVersionManifest.model_validate(_load_json(paths["agent"]))
    ).model_dump(mode="json")
    receipt = _validated_content_hash(_load_json(paths["contract"]), "receipt_hash")
    preflight = _validated_content_hash(_load_json(paths["preflight"]), "receipt_hash")
    attempt = _load_json(paths["attempt"])
    result = attempt.get("result")
    expected_planes = {
        "benchmark_verifier_pass": False,
        "agent_protocol_valid": False,
        "trajectory_eligible": False,
        "infrastructure_valid": True,
        "security_valid": True,
        "sft_admitted": False,
    }
    if (
        report != progress
        or report.get("identity") != "openhands-hwe-v36-provider-canary-v1"
        or report.get("status") != "canary_failed_closed"
        or report.get("failure_reason") != "training-pr2330-s489-v36:six_plane_gate_failed"
        or report.get("report_hash") != _V36_REPORT_HASH
        or report.get("provider_episode_count") != 1
        or report.get("provider_call_count") != 1
        or report.get("attempts") != [attempt]
        or report.get("canary_passed") is not False
        or report.get("formal_collection_allowed") is not False
        or report.get("formal_collection_started") is not False
        or report.get("collection_started") is not False
        or report.get("training_started") is not False
        or report.get("production_training_ready") is not False
        or report.get("benchmark_score_claimed") is not False
        or report.get("heldout_task_ids_loaded") != []
        or agent.get("version_hash") != _V36_AGENT_VERSION_HASH
        or receipt.get("receipt_hash") != _V36_CONTRACT_RECEIPT_HASH
        or preflight.get("receipt_hash") != _V36_PREFLIGHT_RECEIPT_HASH
        or preflight.get("status") != "passed"
        or preflight.get("provider_episode_count") != 0
        or preflight.get("provider_call_count") != 0
        or attempt.get("task_id") != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2330"
        or attempt.get("seed") != 489
        or attempt.get("sample_index") != 5
        or not isinstance(result, dict)
        or any(result.get(key) is not value for key, value in expected_planes.items())
        or attempt.get("protocol_receipt") is not None
        or attempt.get("trajectory_receipt") is not None
        or attempt.get("decision_receipt") is not None
        or attempt.get("token_receipt") is not None
        or attempt.get("exact_64k_eligible") is not False
        or attempt.get("whole_episode_retries") != 0
        or attempt.get("provider_request_retries") != 0
    ):
        raise ConfigurationError("OpenHands v47 v36 failed evidence state changed")
    return report


def _stopped_v37_evidence(root: Path) -> dict[str, Any]:
    """Validate the sealed pre-output v37 infrastructure stop without loading raw failure data."""

    if hash_directory(root) != _V37_STOP_TREE_HASH:
        raise ConfigurationError("OpenHands v47 v37 stop evidence inventory changed")
    receipt_path = _safe_file(root / "stop-receipt.json")
    if hash_bytes(receipt_path.read_bytes()) != _V37_STOP_RECEIPT_SHA256:
        raise ConfigurationError("OpenHands v47 v37 stop evidence file changed")
    receipt = _validated_content_hash(_load_json(receipt_path), "receipt_hash")
    environment = receipt.get("environment")
    repair = receipt.get("repair")
    if (
        receipt.get("format_id") != "verigym_openhands_hwe_v37_pre_output_stop_receipt_v1"
        or receipt.get("identity") != "openhands-hwe-v37-provider-canary-v1"
        or receipt.get("status") != "stopped_infrastructure_invalid_before_output"
        or receipt.get("receipt_hash") != _V37_STOP_RECEIPT_HASH
        or receipt.get("failed_stage") != "tokenizer_import_before_output_and_before_service"
        or receipt.get("root_cause_category")
        != "numpy_native_extension_requires_unavailable_cxxabi"
        or receipt.get("provider_episode_count") != 0
        or receipt.get("provider_call_count") != 0
        or receipt.get("model_process_count") != 0
        or receipt.get("task_attempt_count") != 0
        or receipt.get("task_ids_started") != []
        or receipt.get("authorized_output_path_created") is not False
        or receipt.get("separate_zero_call_preflight_passed") is not True
        or receipt.get("separate_zero_call_preflight_provider_call_count") != 0
        or receipt.get("raw_exception_persisted") is not False
        or receipt.get("formal_collection_allowed") is not False
        or receipt.get("formal_collection_started") is not False
        or receipt.get("collection_started") is not False
        or receipt.get("training_started") is not False
        or receipt.get("production_training_ready") is not False
        or receipt.get("benchmark_score_claimed") is not False
        or not isinstance(environment, dict)
        or environment.get("numpy_version") != "2.5.2"
        or environment.get("transformers_version") != OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION
        or not isinstance(repair, dict)
        or repair.get("pin_numpy_version") != OPENHANDS_V47_NUMPY_VERSION
        or repair.get("pin_pillow_version") != OPENHANDS_V47_PILLOW_VERSION
        or repair.get("provider_invocation_authorized") is not False
        or repair.get("successor_identity_required") is not True
        or repair.get("successor_version") != 38
        or repair.get("tokenizer_import_must_pass_before_output") is not True
    ):
        raise ConfigurationError("OpenHands v47 v37 stop evidence state changed")
    return receipt


def _failed_v38_evidence(root: Path) -> dict[str, Any]:
    """Validate the sealed one-call v38 failure without loading raw provider data."""

    if hash_directory(root) != _V38_TREE_HASH:
        raise ConfigurationError("OpenHands v47 v38 evidence inventory changed")
    paths = {
        "report": root / "canary-report.json",
        "progress": root / "canary-progress.json",
        "agent": root / "agent-version.json",
        "contract": root / "contract-receipt.json",
        "preflight": root / "zero-call-preflight.json",
        "attempt": root / "attempts" / "training-pr3226-s491-v38.json",
        "security": root / "security-scans" / "training-pr3226-s491-v38.json",
    }
    expected_file_hashes = {
        "report": _V38_REPORT_SHA256,
        "progress": _V38_REPORT_SHA256,
        "agent": _V38_AGENT_VERSION_SHA256,
        "contract": _V38_CONTRACT_RECEIPT_SHA256,
        "preflight": _V38_PREFLIGHT_RECEIPT_SHA256,
        "attempt": _V38_ATTEMPT_SHA256,
        "security": _V38_SECURITY_SCAN_SHA256,
    }
    for name, path in paths.items():
        if hash_bytes(_safe_file(path).read_bytes()) != expected_file_hashes[name]:
            raise ConfigurationError("OpenHands v47 v38 evidence file changed")
    report = _validated_content_hash(_load_json(paths["report"]), "report_hash")
    progress = _validated_content_hash(_load_json(paths["progress"]), "report_hash")
    agent = validate_agent_version(
        AgentVersionManifest.model_validate(_load_json(paths["agent"]))
    ).model_dump(mode="json")
    receipt = _validated_content_hash(_load_json(paths["contract"]), "receipt_hash")
    preflight = _validated_content_hash(_load_json(paths["preflight"]), "receipt_hash")
    attempt = _load_json(paths["attempt"])
    security = _validated_content_hash(_load_json(paths["security"]), "report_hash")
    result = attempt.get("result")
    expected_planes = {
        "benchmark_verifier_pass": False,
        "agent_protocol_valid": False,
        "trajectory_eligible": False,
        "infrastructure_valid": True,
        "security_valid": True,
        "sft_admitted": False,
    }
    if (
        report != progress
        or report.get("identity") != "openhands-hwe-v38-numpy-pinned-provider-canary-v1"
        or report.get("status") != "canary_failed_closed"
        or report.get("failure_reason") != "training-pr3226-s491-v38:six_plane_gate_failed"
        or report.get("report_hash") != _V38_REPORT_HASH
        or report.get("source_commit") != _V38_AUTHORIZATION_MERGE
        or report.get("provider_episode_count") != 1
        or report.get("provider_call_count") != 1
        or report.get("attempts") != [attempt]
        or report.get("canary_passed") is not False
        or report.get("formal_collection_allowed") is not False
        or report.get("formal_collection_started") is not False
        or report.get("collection_started") is not False
        or report.get("training_started") is not False
        or report.get("production_training_ready") is not False
        or report.get("benchmark_score_claimed") is not False
        or report.get("heldout_task_ids_loaded") != []
        or agent.get("version_hash") != _V38_AGENT_VERSION_HASH
        or receipt.get("receipt_hash") != _V38_CONTRACT_RECEIPT_HASH
        or preflight.get("receipt_hash") != _V38_PREFLIGHT_RECEIPT_HASH
        or preflight.get("status") != "passed"
        or preflight.get("provider_episode_count") != 0
        or preflight.get("provider_call_count") != 0
        or attempt.get("task_id") != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3226"
        or attempt.get("seed") != 491
        or attempt.get("sample_index") != 7
        or not isinstance(result, dict)
        or any(result.get(key) is not value for key, value in expected_planes.items())
        or attempt.get("protocol_receipt") is not None
        or attempt.get("trajectory_receipt") is not None
        or attempt.get("decision_receipt") is not None
        or attempt.get("token_receipt") is not None
        or attempt.get("exact_64k_eligible") is not False
        or attempt.get("whole_episode_retries") != 0
        or attempt.get("provider_request_retries") != 0
        or security.get("report_hash") != _V38_SECURITY_SCAN_HASH
        or security.get("gate") != "pass"
        or security.get("hard_secret_leak_count") != 0
        or security.get("scanner_error_count") != 0
        or security.get("proxy_values_persisted_or_hashed") is not False
    ):
        raise ConfigurationError("OpenHands v47 v38 failed evidence state changed")
    return report


def _failed_v39_evidence(root: Path) -> dict[str, Any]:
    """Validate the sealed v39 SDK-normalized empty-content failure."""

    if hash_directory(root) != _V39_TREE_HASH:
        raise ConfigurationError("OpenHands v47 v39 evidence inventory changed")
    paths = {
        "report": root / "canary-report.json",
        "progress": root / "canary-progress.json",
        "agent": root / "agent-version.json",
        "contract": root / "contract-receipt.json",
        "preflight": root / "zero-call-preflight.json",
        "attempt": root / "attempts" / "training-pr3231-s492-v39.json",
        "security": root / "security-scans" / "training-pr3231-s492-v39.json",
    }
    expected_file_hashes = {
        "report": _V39_REPORT_SHA256,
        "progress": _V39_REPORT_SHA256,
        "agent": _V39_AGENT_VERSION_SHA256,
        "contract": _V39_CONTRACT_RECEIPT_SHA256,
        "preflight": _V39_PREFLIGHT_RECEIPT_SHA256,
        "attempt": _V39_ATTEMPT_SHA256,
        "security": _V39_SECURITY_SCAN_SHA256,
    }
    for name, path in paths.items():
        if hash_bytes(_safe_file(path).read_bytes()) != expected_file_hashes[name]:
            raise ConfigurationError("OpenHands v47 v39 evidence file changed")
    report = _validated_content_hash(_load_json(paths["report"]), "report_hash")
    progress = _validated_content_hash(_load_json(paths["progress"]), "report_hash")
    agent = validate_agent_version(
        AgentVersionManifest.model_validate(_load_json(paths["agent"]))
    ).model_dump(mode="json")
    receipt = _validated_content_hash(_load_json(paths["contract"]), "receipt_hash")
    preflight = _validated_content_hash(_load_json(paths["preflight"]), "receipt_hash")
    attempt = _load_json(paths["attempt"])
    security = _validated_content_hash(_load_json(paths["security"]), "report_hash")
    result = attempt.get("result")
    expected_planes = {
        "benchmark_verifier_pass": False,
        "agent_protocol_valid": False,
        "trajectory_eligible": False,
        "infrastructure_valid": True,
        "security_valid": True,
        "sft_admitted": False,
    }
    if (
        report != progress
        or report.get("identity") != "openhands-hwe-v39-atomic-shape-recovery-provider-canary-v1"
        or report.get("status") != "canary_failed_closed"
        or report.get("failure_reason") != "training-pr3231-s492-v39:six_plane_gate_failed"
        or report.get("report_hash") != _V39_REPORT_HASH
        or report.get("source_commit") != _V39_AUTHORIZATION_MERGE
        or report.get("provider_episode_count") != 1
        or report.get("provider_call_count") != 1
        or report.get("attempts") != [attempt]
        or report.get("canary_passed") is not False
        or report.get("formal_collection_allowed") is not False
        or report.get("formal_collection_started") is not False
        or report.get("collection_started") is not False
        or report.get("training_started") is not False
        or report.get("production_training_ready") is not False
        or report.get("benchmark_score_claimed") is not False
        or report.get("heldout_task_ids_loaded") != []
        or agent.get("version_hash") != _V39_AGENT_VERSION_HASH
        or receipt.get("receipt_hash") != _V39_CONTRACT_RECEIPT_HASH
        or preflight.get("receipt_hash") != _V39_PREFLIGHT_RECEIPT_HASH
        or preflight.get("status") != "passed"
        or preflight.get("provider_episode_count") != 0
        or preflight.get("provider_call_count") != 0
        or attempt.get("task_id") != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3231"
        or attempt.get("seed") != 492
        or attempt.get("sample_index") != 8
        or not isinstance(result, dict)
        or any(result.get(key) is not value for key, value in expected_planes.items())
        or attempt.get("protocol_receipt") is not None
        or attempt.get("trajectory_receipt") is not None
        or attempt.get("decision_receipt") is not None
        or attempt.get("token_receipt") is not None
        or attempt.get("exact_64k_eligible") is not False
        or attempt.get("whole_episode_retries") != 0
        or attempt.get("provider_request_retries") != 0
        or security.get("report_hash") != _V39_SECURITY_SCAN_HASH
        or security.get("gate") != "pass"
        or security.get("hard_secret_leak_count") != 0
        or security.get("scanner_error_count") != 0
        or security.get("proxy_values_persisted_or_hashed") is not False
    ):
        raise ConfigurationError("OpenHands v47 v39 failed evidence state changed")
    return report


def _failed_v41_evidence(root: Path) -> dict[str, Any]:
    """Validate the sealed v41 PR-2549 ordinary token-budget failure."""

    if hash_directory(root) != _V41_TREE_HASH:
        raise ConfigurationError("OpenHands v47 v41 evidence inventory changed")
    paths = {
        "report": root / "canary-report.json",
        "progress": root / "canary-progress.json",
        "agent": root / "agent-version.json",
        "contract": root / "contract-receipt.json",
        "preflight": root / "zero-call-preflight.json",
        "attempt": root / "attempts" / "training-pr2549-s493-v41.json",
        "security": root / "security-scans" / "training-pr2549-s493-v41.json",
    }
    expected_file_hashes = {
        "report": _V41_REPORT_SHA256,
        "progress": _V41_REPORT_SHA256,
        "agent": _V41_AGENT_VERSION_SHA256,
        "contract": _V41_CONTRACT_RECEIPT_SHA256,
        "preflight": _V41_PREFLIGHT_RECEIPT_SHA256,
        "attempt": _V41_ATTEMPT_SHA256,
        "security": _V41_SECURITY_SCAN_SHA256,
    }
    for name, path in paths.items():
        if hash_bytes(_safe_file(path).read_bytes()) != expected_file_hashes[name]:
            raise ConfigurationError("OpenHands v47 v41 evidence file changed")
    report = _validated_content_hash(_load_json(paths["report"]), "report_hash")
    progress = _validated_content_hash(_load_json(paths["progress"]), "report_hash")
    agent = validate_agent_version(
        AgentVersionManifest.model_validate(_load_json(paths["agent"]))
    ).model_dump(mode="json")
    receipt = _validated_content_hash(_load_json(paths["contract"]), "receipt_hash")
    preflight = _validated_content_hash(_load_json(paths["preflight"]), "receipt_hash")
    attempt = _load_json(paths["attempt"])
    security = _validated_content_hash(_load_json(paths["security"]), "report_hash")
    result = attempt.get("result")
    expected_planes = {
        "benchmark_verifier_pass": False,
        "agent_protocol_valid": False,
        "trajectory_eligible": False,
        "infrastructure_valid": True,
        "security_valid": True,
        "sft_admitted": False,
    }
    if (
        report != progress
        or report.get("identity") != "openhands-hwe-v41-atomic-shape-recovery-provider-canary-v1"
        or report.get("status") != "canary_failed_closed"
        or report.get("failure_reason") != "training-pr2549-s493-v41:six_plane_gate_failed"
        or report.get("report_hash") != _V41_REPORT_HASH
        or report.get("source_commit") != _V41_AUTHORIZATION_MERGE
        or report.get("provider_episode_count") != 1
        or report.get("provider_call_count") != 42
        or report.get("attempts") != [attempt]
        or report.get("canary_passed") is not False
        or report.get("formal_collection_allowed") is not False
        or report.get("formal_collection_started") is not False
        or report.get("collection_started") is not False
        or report.get("training_started") is not False
        or report.get("production_training_ready") is not False
        or report.get("benchmark_score_claimed") is not False
        or report.get("heldout_task_ids_loaded") != []
        or report.get("training_task_disposition") != "replace_after_failed_canary"
        or agent.get("version_hash") != _V41_AGENT_VERSION_HASH
        or receipt.get("receipt_hash") != _V41_CONTRACT_RECEIPT_HASH
        or preflight.get("receipt_hash") != _V41_PREFLIGHT_RECEIPT_HASH
        or preflight.get("status") != "passed"
        or preflight.get("provider_episode_count") != 0
        or preflight.get("provider_call_count") != 0
        or attempt.get("task_id") != "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549"
        or attempt.get("seed") != 493
        or attempt.get("sample_index") != 9
        or attempt.get("run_hash") != _V41_ATTEMPT_RUN_HASH
        or not isinstance(result, dict)
        or any(result.get(key) is not value for key, value in expected_planes.items())
        or attempt.get("protocol_receipt") is not None
        or attempt.get("trajectory_receipt") is not None
        or attempt.get("decision_receipt") is not None
        or attempt.get("token_receipt") is not None
        or attempt.get("exact_64k_eligible") is not False
        or attempt.get("truncation_applied") is not False
        or attempt.get("whole_episode_retries") != 0
        or attempt.get("provider_request_retries") != 0
        or security.get("report_hash") != _V41_SECURITY_SCAN_HASH
        or security.get("gate") != "pass"
        or security.get("hard_secret_leak_count") != 0
        or security.get("scanner_error_count") != 0
        or security.get("proxy_values_persisted_or_hashed") is not False
    ):
        raise ConfigurationError("OpenHands v47 v41 failed evidence state changed")
    return report


def _control_plane_contract() -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v47_control_plane_contract_v1",
        "broker_root": _BROKER_ROOT,
        "maximum_encoded_broker_root_bytes": 72,
        "mcp_pythonpath_entries": list(_MCP_PYTHONPATH_ENTRIES),
        "maximum_mcp_pythonpath_entries": 16,
        "maximum_encoded_mcp_pythonpath_bytes": 4096,
        "paths_must_exist": True,
        "paths_must_be_non_symlink": True,
        "preflight_receipt_format": "verigym_openhands_hwe_v47_zero_call_preflight_v1",
        "raw_exception_persisted": False,
    }
    return {**base, "contract_hash": content_hash(base)}


def _expected_authorization() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "format_id": OPENHANDS_V47_APPROVAL_FORMAT,
        "status": "authorized_pending_provider_canary",
        "identity": OPENHANDS_V47_IDENTITY,
        "v33_materialization_evidence": {
            "audit_merge_commit": _V33_AUDIT_MERGE,
            "audit_file_sha256": _V33_AUDIT_FILE_SHA256,
            "evidence_tree_hash": _V33_TREE_HASH,
            "progress_hash": _V33_PROGRESS_HASH,
            "progress_file_sha256": _V33_PROGRESS_SHA256,
            "catalog_hash": _V33_CATALOG_HASH,
            "catalog_file_sha256": _V33_CATALOG_SHA256,
        },
        "failed_v36_evidence": {
            "audit_merge_commit": _V36_AUDIT_MERGE,
            "audit_file_sha256": _V36_AUDIT_FILE_SHA256,
            "evidence_tree_hash": _V36_TREE_HASH,
            "report_hash": _V36_REPORT_HASH,
            "report_file_sha256": _V36_REPORT_SHA256,
            "agent_version_hash": _V36_AGENT_VERSION_HASH,
            "agent_version_file_sha256": _V36_AGENT_VERSION_SHA256,
            "contract_receipt_hash": _V36_CONTRACT_RECEIPT_HASH,
            "contract_receipt_file_sha256": _V36_CONTRACT_RECEIPT_SHA256,
            "preflight_receipt_hash": _V36_PREFLIGHT_RECEIPT_HASH,
            "preflight_receipt_file_sha256": _V36_PREFLIGHT_RECEIPT_SHA256,
            "attempt_file_sha256": _V36_ATTEMPT_SHA256,
            "provider_episode_count": 1,
            "provider_call_count": 1,
            "task_attempt_count": 1,
            "failed_task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2330",
            "failed_task_retry_authorized": False,
        },
        "v36_root_cause_evidence": {
            "merge_commit": _V36_ROOT_CAUSE_MERGE,
            "audit_file_sha256": _V36_ROOT_CAUSE_FILE_SHA256,
            "diagnosis": "v19_rejected_single_tool_call_with_public_visible_text",
            "successor_protocol": "required_tool_public_thought_content_recovery_v20",
        },
        "stopped_v37_evidence": {
            "audit_merge_commit": _V37_STOP_AUDIT_MERGE,
            "audit_file_sha256": _V37_STOP_AUDIT_FILE_SHA256,
            "evidence_tree_hash": _V37_STOP_TREE_HASH,
            "receipt_hash": _V37_STOP_RECEIPT_HASH,
            "receipt_file_sha256": _V37_STOP_RECEIPT_SHA256,
            "status": "stopped_infrastructure_invalid_before_output",
            "provider_episode_count": 0,
            "provider_call_count": 0,
            "task_attempt_count": 0,
            "successor_version": 38,
        },
        "failed_v38_evidence": {
            "authorization_merge_commit": _V38_AUTHORIZATION_MERGE,
            "failure_audit_merge_commit": _V38_FAILURE_AUDIT_MERGE,
            "failure_audit_file_sha256": _V38_FAILURE_AUDIT_FILE_SHA256,
            "evidence_tree_hash": _V38_TREE_HASH,
            "report_hash": _V38_REPORT_HASH,
            "report_file_sha256": _V38_REPORT_SHA256,
            "agent_version_hash": _V38_AGENT_VERSION_HASH,
            "agent_version_file_sha256": _V38_AGENT_VERSION_SHA256,
            "contract_receipt_hash": _V38_CONTRACT_RECEIPT_HASH,
            "contract_receipt_file_sha256": _V38_CONTRACT_RECEIPT_SHA256,
            "preflight_receipt_hash": _V38_PREFLIGHT_RECEIPT_HASH,
            "preflight_receipt_file_sha256": _V38_PREFLIGHT_RECEIPT_SHA256,
            "attempt_file_sha256": _V38_ATTEMPT_SHA256,
            "security_scan_hash": _V38_SECURITY_SCAN_HASH,
            "security_scan_file_sha256": _V38_SECURITY_SCAN_SHA256,
            "provider_episode_count": 1,
            "provider_call_count": 1,
            "task_attempt_count": 1,
            "failed_task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3226",
            "failed_task_retry_authorized": False,
            "validation_task_started": False,
        },
        "failed_v39_evidence": {
            "authorization_merge_commit": _V39_AUTHORIZATION_MERGE,
            "failure_audit_merge_commit": _V39_FAILURE_AUDIT_MERGE,
            "failure_audit_file_sha256": _V39_FAILURE_AUDIT_FILE_SHA256,
            "evidence_tree_hash": _V39_TREE_HASH,
            "report_hash": _V39_REPORT_HASH,
            "report_file_sha256": _V39_REPORT_SHA256,
            "agent_version_hash": _V39_AGENT_VERSION_HASH,
            "agent_version_file_sha256": _V39_AGENT_VERSION_SHA256,
            "contract_receipt_hash": _V39_CONTRACT_RECEIPT_HASH,
            "contract_receipt_file_sha256": _V39_CONTRACT_RECEIPT_SHA256,
            "preflight_receipt_hash": _V39_PREFLIGHT_RECEIPT_HASH,
            "preflight_receipt_file_sha256": _V39_PREFLIGHT_RECEIPT_SHA256,
            "attempt_file_sha256": _V39_ATTEMPT_SHA256,
            "security_scan_hash": _V39_SECURITY_SCAN_HASH,
            "security_scan_file_sha256": _V39_SECURITY_SCAN_SHA256,
            "provider_episode_count": 1,
            "provider_call_count": 1,
            "task_attempt_count": 1,
            "failed_task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-3231",
            "failed_task_retry_authorized": False,
            "validation_task_started": False,
        },
        "failed_v41_evidence": {
            "authorization_merge_commit": _V41_AUTHORIZATION_MERGE,
            "failure_audit_merge_commit": _V41_FAILURE_AUDIT_MERGE,
            "failure_audit_file_sha256": _V41_FAILURE_AUDIT_FILE_SHA256,
            "post_merge_main_run_id": _V41_MAIN_RUN_ID,
            "post_merge_main_all_eight_classes_passed": True,
            "evidence_tree_hash": _V41_TREE_HASH,
            "report_hash": _V41_REPORT_HASH,
            "report_file_sha256": _V41_REPORT_SHA256,
            "agent_version_hash": _V41_AGENT_VERSION_HASH,
            "agent_version_file_sha256": _V41_AGENT_VERSION_SHA256,
            "contract_receipt_hash": _V41_CONTRACT_RECEIPT_HASH,
            "contract_receipt_file_sha256": _V41_CONTRACT_RECEIPT_SHA256,
            "preflight_receipt_hash": _V41_PREFLIGHT_RECEIPT_HASH,
            "preflight_receipt_file_sha256": _V41_PREFLIGHT_RECEIPT_SHA256,
            "attempt_run_hash": _V41_ATTEMPT_RUN_HASH,
            "attempt_file_sha256": _V41_ATTEMPT_SHA256,
            "security_scan_hash": _V41_SECURITY_SCAN_HASH,
            "security_scan_file_sha256": _V41_SECURITY_SCAN_SHA256,
            "provider_episode_count": 1,
            "provider_call_count": 42,
            "task_attempt_count": 1,
            "failed_task_id": "hwe-bench/repo-repair-v1/openhwgroup__cva6__pr-2549",
            "failed_task_retry_authorized": False,
            "validation_task_started": False,
        },
        "v46_materialization_evidence": {
            "authorization_merge_commit": _V46_AUTHORIZATION_MERGE,
            "result_audit_merge_commit": _V46_RESULT_AUDIT_MERGE,
            "result_audit_file_sha256": _V46_RESULT_AUDIT_FILE_SHA256,
            "post_merge_main_run_id": _V46_MAIN_RUN_ID,
            "post_merge_main_all_eight_classes_passed": True,
            "evidence_tree_hash": _V46_TREE_HASH,
            "progress_hash": _V46_PROGRESS_HASH,
            "progress_file_sha256": _V46_PROGRESS_SHA256,
            "catalog_hash": _V46_CATALOG_HASH,
            "catalog_file_sha256": _V46_CATALOG_SHA256,
            "contract_hash": _V46_CONTRACT_HASH,
            "contract_file_sha256": _V46_CONTRACT_SHA256,
            "provider_episode_count": 0,
            "provider_call_count": 0,
        },
        "v22_protocol_repair_evidence": {
            "merge_commit": _V22_PROTOCOL_MERGE,
            "audit_file_sha256": _V22_PROTOCOL_AUDIT_SHA256,
            "post_merge_main_run_id": _V22_PROTOCOL_MAIN_RUN_ID,
            "post_merge_main_all_eight_classes_passed": True,
            "predecessor_protocol": "required_tool_atomic_shape_recovery_v21",
            "successor_protocol": OPENHANDS_V22_TOOL_CHOICE_POLICY,
            "provider_invocation_authorized_by_repair": False,
        },
        "control_plane": _control_plane_contract(),
        "command_image_locks": [
            {"task_id": task_id, **copy.deepcopy(_LOCK_INPUTS[task_id])} for task_id in _TASKS
        ],
        "input_locks": {
            "training_source_image_lock_sha256": _TRAINING_SOURCE_LOCK_SHA256,
            "validation_source_image_lock_sha256": _VALIDATION_SOURCE_LOCK_SHA256,
            "base_model_lock_file_sha256": _BASE_MODEL_LOCK_SHA256,
            "base_model_snapshot_hash": _MODEL_SNAPSHOT_HASH,
            "tokenizer_hash": _TOKENIZER_HASH,
        },
        "software": {
            "model": OPENHANDS_V19_CANARY_MODEL,
            "model_identity": OPENHANDS_V19_CANARY_MODEL_IDENTITY,
            "openhands_sdk_version": OPENHANDS_V19_CANARY_SDK_VERSION,
            "litellm_version": OPENHANDS_V19_CANARY_LITELLM_VERSION,
            "tiktoken_version": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
            "transformers_version": OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
            "numpy_version": OPENHANDS_V47_NUMPY_VERSION,
            "pillow_version": OPENHANDS_V47_PILLOW_VERSION,
        },
        "schedule": {
            "campaign_id": OPENHANDS_V47_CANARY_CAMPAIGN_ID,
            "agent_version_id": OPENHANDS_V47_CANARY_AGENT_VERSION_ID,
            "task_ids": list(_TASKS),
            "roles": ["training", "validation"],
            "seed": OPENHANDS_V47_CANARY_SEED,
            "sample_index": OPENHANDS_V47_CANARY_SAMPLE_INDEX,
            "maximum_provider_episodes": 2,
            "pr2330_retry_authorized": False,
            "pr3226_already_consumed_as_canary": True,
            "pr3226_retry_authorized": False,
            "pr3231_consumed_as_canary": True,
            "pr3231_retry_authorized": False,
            "pr2549_consumed_as_canary": True,
            "pr2549_retry_authorized": False,
            "pr2802_new_only_to_current_identity": True,
            "pr2802_historical_trajectory_relabelled": False,
            "pr2802_success_imports_without_formal_reexecution": True,
            "pr2802_failure_requires_formal_replacement": True,
            "validation_pr3204_previously_started": False,
        },
        "runtime": {
            "command_role": "credential_free_command_image",
            "command_execution_backend": OPENHANDS_V47_COMMAND_EXECUTION_BACKEND,
            "external_agent_process_available": False,
            "codex_present": False,
            "provider_credentials_in_command_container": False,
            "network": "none",
        },
        "provider_budget": {
            "temperature": 0,
            "max_provider_calls_per_episode": 64,
            "max_provider_tokens_per_episode": 1_000_000,
            "max_context_tokens": 65_536,
            "max_output_tokens": 2_048,
            "provider_request_retries": 0,
            "whole_episode_retries": 0,
        },
        "protocol": {
            "profile": OPENHANDS_V22_TOOL_CHOICE_POLICY,
            "ordinary_tool_choice": "required",
            "maximum_tool_calls_per_response": 1,
            "recoverable_provider_tool_call_count": 2,
            "recoverable_empty_text_part_counts": [0, 1],
            "normalized_empty_text_content_allowed": True,
            "nonempty_or_whitespace_text_in_shape_recovery_allowed": False,
            "multiple_tool_response_rejected_atomically": True,
            "rejected_sibling_tool_calls_dispatched": False,
            "public_visible_tool_thought_allowed": True,
            "public_visible_tool_thought_supervised": True,
            "private_reasoning_rejected": True,
            "malformed_or_duplicate_json_rejected": True,
            "safe_shape_only": True,
            "raw_model_content_persisted": False,
            "raw_tool_arguments_persisted": False,
            "combined_shape_recovery_budget": 1,
            "content_only_recovery_budget": 1,
            "multi_tool_shape_recovery_budget": 1,
            "synthetic_shape_recovery_assistant_supervised": False,
        },
        "required_controls": {
            "clean_merged_source_commit": True,
            "exact_v33_result_chain": True,
            "exact_failed_v36_result_chain": True,
            "exact_v36_root_cause_chain": True,
            "exact_stopped_v37_result_chain": True,
            "exact_failed_v38_result_chain": True,
            "exact_failed_v39_result_chain": True,
            "exact_failed_v41_result_chain": True,
            "exact_v46_result_chain": True,
            "exact_v22_protocol_repair_chain": True,
            "exact_runtime_dependency_versions": True,
            "training_task_new_to_current_identity": True,
            "historical_trajectory_relabelled": False,
            "explicit_command_backend_capability": True,
            "exact_task_source_command_image_binding": True,
            "control_plane_validated_before_output": True,
            "redacted_zero_call_preflight_receipt": True,
            "stop_after_first_failed_gate": True,
            "all_six_result_planes_required": True,
            "runtime_network_none": True,
            "security_scan_before_admission": True,
            "exact_64k_no_truncation": True,
            "decision_only_loss_mask": True,
            "atomic_per_task_progress": True,
            "provider_values_never_persisted_or_hashed": True,
            "heldout_tasks_loaded": False,
        },
        "authorized_actions": {
            "invoke_provider": True,
            "execute_fixed_two_task_canary": True,
            "retry_pr2330": False,
            "consume_pr3226_as_canary": False,
            "retry_pr3226": False,
            "retry_pr3231": False,
            "retry_pr2549": False,
            "consume_pr2802_as_canary": True,
            "import_successful_pr2802_canary_without_formal_reexecution": True,
            "relabel_historical_pr2802_trajectory": False,
            "consume_any_other_reserve": False,
            "create_fallback_identity": False,
            "start_formal_collection": False,
            "start_training": False,
            "load_heldout_tasks": False,
        },
        "failure_policy": "stop_after_first_failed_gate_no_retry_freeze_identity",
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "training_started": False,
        "production_training_ready": False,
        "benchmark_score_claimed": False,
    }


def _validated_authorization(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop("authorization_hash", None)
    if observed != OPENHANDS_V47_APPROVAL_HASH or content_hash(result) != observed:
        raise ConfigurationError("OpenHands v47 authorization identity changed")
    if result != _expected_authorization():
        raise ConfigurationError("OpenHands v47 authorization policy changed")
    return {**result, "authorization_hash": observed}


def _validated_source(path: Path, *, expected_lock_sha256: str) -> Path:
    root = _safe_directory(path, "source")
    if hash_bytes(_safe_file(root / "image-lock.json").read_bytes()) != expected_lock_sha256:
        raise ConfigurationError("OpenHands v47 source image lock changed")
    return root


def _contract_receipt(
    contract: dict[str, Any], locks: dict[str, HweCommandImageLock]
) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v47_contract_receipt_v1",
        "v33_catalog_hash": _V33_CATALOG_HASH,
        "failed_v36_report_hash": _V36_REPORT_HASH,
        "v36_root_cause_merge_commit": _V36_ROOT_CAUSE_MERGE,
        "stopped_v37_receipt_hash": _V37_STOP_RECEIPT_HASH,
        "failed_v38_report_hash": _V38_REPORT_HASH,
        "failed_v38_audit_merge_commit": _V38_FAILURE_AUDIT_MERGE,
        "failed_v39_report_hash": _V39_REPORT_HASH,
        "failed_v39_audit_merge_commit": _V39_FAILURE_AUDIT_MERGE,
        "failed_v41_report_hash": _V41_REPORT_HASH,
        "failed_v41_audit_merge_commit": _V41_FAILURE_AUDIT_MERGE,
        "v46_evidence_tree_hash": _V46_TREE_HASH,
        "v46_catalog_hash": _V46_CATALOG_HASH,
        "v46_contract_hash": _V46_CONTRACT_HASH,
        "v46_result_audit_merge_commit": _V46_RESULT_AUDIT_MERGE,
        "v22_protocol_merge_commit": _V22_PROTOCOL_MERGE,
        "v22_protocol_audit_sha256": _V22_PROTOCOL_AUDIT_SHA256,
        "v47_contract_hash": contract["contract_hash"],
        "control_plane_contract_hash": _control_plane_contract()["contract_hash"],
        "campaign_id": OPENHANDS_V47_CANARY_CAMPAIGN_ID,
        "agent_version_id": OPENHANDS_V47_CANARY_AGENT_VERSION_ID,
        "task_bindings": copy.deepcopy(contract["task_bindings"]),
        "command_image_lock_hashes": {task_id: locks[task_id].lock_hash for task_id in _TASKS},
        "schedule": copy.deepcopy(contract["schedule"]),
        "protocol_profile": OPENHANDS_V22_TOOL_CHOICE_POLICY,
        "command_execution_backend": OPENHANDS_V47_COMMAND_EXECUTION_BACKEND,
        "pr2330_retry_authorized": False,
        "pr3226_retry_authorized": False,
        "pr3231_retry_authorized": False,
        "training_task_consumed_by_canary": _TRAINING_TASK,
        "training_task_success_imports_without_formal_reexecution": True,
        "training_task_failure_requires_formal_replacement": True,
        "historical_trajectory_relabelled": False,
        "numpy_version": OPENHANDS_V47_NUMPY_VERSION,
        "pillow_version": OPENHANDS_V47_PILLOW_VERSION,
        "heldout_task_ids_loaded": [],
    }
    return {**base, "receipt_hash": content_hash(base)}


def _runtime_config(lock: HweCommandImageLock) -> DockerRuntimeConfig:
    return build_hwe_command_runtime_config(
        lock,
        runtime_user=f"{os.getuid()}:{os.getgid()}",
        execution_backend=OPENHANDS_V47_COMMAND_EXECUTION_BACKEND,
    )


def _validated_control_plane_environment() -> dict[str, Any]:
    from verigym_openhands.hwe_agent import _configured_control_root, _configured_mcp_pythonpath

    expected_pythonpath = os.pathsep.join(_MCP_PYTHONPATH_ENTRIES)
    if os.environ.get(_BROKER_ROOT_ENV) != _BROKER_ROOT:
        raise ConfigurationError("OpenHands v47 broker root contract changed")
    if os.environ.get(_MCP_PYTHONPATH_ENV) != expected_pythonpath:
        raise ConfigurationError("OpenHands v47 MCP Python path contract changed")
    if str(_configured_control_root()) != _BROKER_ROOT:
        raise ConfigurationError("OpenHands v47 resolved broker root changed")
    if _configured_mcp_pythonpath() != expected_pythonpath:
        raise ConfigurationError("OpenHands v47 resolved MCP Python path changed")
    return _control_plane_contract()


def _zero_call_preflight(
    root: Path,
    locks: dict[str, HweCommandImageLock],
    sources: dict[str, Path],
) -> None:
    completed: list[str] = []
    stage = "control_plane"
    try:
        control_plane = _validated_control_plane_environment()
        completed.append(stage)
        for task_id in _TASKS:
            suffix = task_id.rsplit("-", 1)[-1]
            stage = f"command_image_pr_{suffix}"
            runtime = DockerRuntime(_runtime_config(locks[task_id]))
            try:
                runtime.prepare(f"openhands-v47-preflight-{suffix}")
                _validate_runtime_manifest(runtime.environment_summary(), locks[task_id])
                completed.append(stage)
                stage = f"adapter_start_pr_{suffix}"
                session = runtime.create_session(
                    SessionSpec(source_dir=str(sources[task_id]), label="agent")
                )
                try:
                    bridge = RuntimeExternalAgentBridge(
                        session=session,
                        artifact_root=root / "preflight-adapter-artifacts" / f"pr-{suffix}",
                        isolation_level="docker_standard",
                        policy=WorkspacePolicy(editable_globs=("**/*",)),
                        trace=TraceWriter(
                            root / "preflight-traces" / f"pr-{suffix}.jsonl",
                            f"openhands-v47-preflight-{suffix}",
                        ),
                    )
                    if _validated_hwe_runtime_bridge(bridge) is not bridge:
                        raise ConfigurationError("OpenHands v47 adapter-start bridge changed")
                finally:
                    session.close()
            finally:
                runtime.close()
            completed.append(stage)
    except Exception as exc:
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_openhands_hwe_v47_zero_call_preflight_v1",
            "status": "failed",
            "control_plane_contract_hash": _control_plane_contract()["contract_hash"],
            "completed_stages": completed,
            "failed_stage": stage,
            "exception_type": type(exc).__name__,
            "provider_episode_count": 0,
            "provider_call_count": 0,
            "raw_exception_persisted": False,
        }
        atomic_dump_json(
            root / "zero-call-preflight.json",
            {**base, "receipt_hash": content_hash(base)},
        )
        raise
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v47_zero_call_preflight_v1",
        "status": "passed",
        "control_plane_contract_hash": control_plane["contract_hash"],
        "completed_stages": completed,
        "failed_stage": None,
        "exception_type": None,
        "provider_episode_count": 0,
        "provider_call_count": 0,
        "raw_exception_persisted": False,
    }
    atomic_dump_json(
        root / "zero-call-preflight.json", {**base, "receipt_hash": content_hash(base)}
    )


def _validate_runtime_manifest(value: dict[str, Any], lock: HweCommandImageLock) -> None:
    roles = value.get("docker_role_images")
    if not isinstance(roles, dict):
        raise ConfigurationError("OpenHands v47 runtime role evidence is missing")
    command = roles.get("command")
    if (
        roles.get("external_agent") is not None
        or not isinstance(command, dict)
        or command.get("resolved_image_id") != lock.derived_command_image_id
        or value.get("external_agent_execution_backend") != "runtime_external_process_unavailable"
        or value.get("external_agent_command_execution_backend")
        != OPENHANDS_V47_COMMAND_EXECUTION_BACKEND
    ):
        raise ConfigurationError("OpenHands v47 command runtime evidence changed")


def _service() -> VeriGym:
    registries = build_registries(discover_external=True)
    if "hwe-bench" not in registries.suites.names():
        from verigym_hwe_bench.adapter import HweBenchSuite

        registries.suites.register(HweBenchSuite())
    if "openhands-hwe-agent" not in registries.agents.names():
        from verigym_openhands.hwe_agent import OpenHandsHweAgentAdapter

        registries.agents.register(OpenHandsHweAgentAdapter())
    return VeriGym(registries)


def _require_opt_in(campaign_id: str) -> None:
    if os.environ.get(OPENHANDS_V47_CANARY_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{OPENHANDS_V47_CANARY_OPT_IN_ENV}=1 is required")
    if campaign_id != OPENHANDS_V47_CANARY_CAMPAIGN_ID:
        raise ConfigurationError("OpenHands v47 campaign identity changed")
    _validated_control_plane_environment()
    if not os.environ.get(OPENHANDS_V19_CANARY_BASE_URL_ENV) or not os.environ.get(
        OPENHANDS_V19_CANARY_API_KEY_ENV
    ):
        raise ConfigurationError("OpenHands v47 provider environment is incomplete")
    expected = {
        "openhands-sdk": OPENHANDS_V19_CANARY_SDK_VERSION,
        "litellm": OPENHANDS_V19_CANARY_LITELLM_VERSION,
        "tiktoken": OPENHANDS_V19_CANARY_TIKTOKEN_VERSION,
        "transformers": OPENHANDS_V19_CANARY_TRANSFORMERS_VERSION,
        "numpy": OPENHANDS_V47_NUMPY_VERSION,
        "pillow": OPENHANDS_V47_PILLOW_VERSION,
    }
    for package, version in expected.items():
        if importlib.metadata.version(package) != version:
            raise ConfigurationError(f"OpenHands v47 {package} version changed")


def _provider_values() -> tuple[str, str]:
    return (
        os.environ[OPENHANDS_V19_CANARY_BASE_URL_ENV],
        os.environ[OPENHANDS_V19_CANARY_API_KEY_ENV],
    )


def _scan_provider_values(root: Path) -> dict[str, Any]:
    values = tuple(value.encode() for value in _provider_values())
    files = 0
    byte_count = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ConfigurationError("OpenHands v47 artifact contains a symlink")
        if not path.is_file():
            continue
        data = path.read_bytes()
        files += 1
        byte_count += len(data)
        if any(value in data for value in values):
            raise ConfigurationError("provider value reached OpenHands v47 artifacts")
    return {
        "passed": True,
        "provider_value_count_scanned": len(values),
        "file_count_scanned": files,
        "byte_count_scanned": byte_count,
        "provider_value_hit_count": 0,
        "provider_values_persisted_or_hashed": False,
    }


def _merged_source_commit() -> str:
    repository = Path(__file__).resolve().parents[1]
    for relative in _REQUIRED_MERGED_PATHS:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tracked != relative:
            raise ConfigurationError("OpenHands v47 required merged path changed")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=repository, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    upstream = subprocess.run(
        ["git", "rev-parse", "origin/main"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for predecessor in (
        _V33_AUDIT_MERGE,
        _V36_AUDIT_MERGE,
        _V36_ROOT_CAUSE_MERGE,
        _V37_STOP_AUDIT_MERGE,
        _V38_AUTHORIZATION_MERGE,
        _V38_FAILURE_AUDIT_MERGE,
        _V39_AUTHORIZATION_MERGE,
        _V39_FAILURE_AUDIT_MERGE,
        _V41_AUTHORIZATION_MERGE,
        _V41_FAILURE_AUDIT_MERGE,
        _V46_AUTHORIZATION_MERGE,
        _V46_RESULT_AUDIT_MERGE,
        _V22_PROTOCOL_MERGE,
    ):
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", predecessor, head],
            cwd=repository,
            check=True,
        )
    v33_audit = (
        repository / "docs/audits/2026-09-01_openhands-v33-codex-free-materialization-passed.md"
    )
    v36_audit = repository / "docs/audits/2026-09-01_openhands-v36-provider-canary-failed-closed.md"
    root_cause = repository / "docs/audits/2026-09-01_openhands-v36-provider-response-root-cause.md"
    v37_stop = (
        repository / "docs/audits/2026-09-01_openhands-v37-provider-canary-stopped-before-output.md"
    )
    v38_failure = (
        repository / "docs/audits/2026-09-01_openhands-v38-provider-canary-failed-closed.md"
    )
    v39_failure = (
        repository / "docs/audits/2026-09-01_openhands-v39-provider-canary-failed-closed.md"
    )
    v41_failure = (
        repository / "docs/audits/2026-09-01_openhands-v41-provider-canary-failed-closed.md"
    )
    v46_result = repository / (
        "docs/audits/2026-09-01_openhands-v46-pr2802-canary-materialization-result.md"
    )
    v22_protocol = (
        repository / "docs/audits/2026-09-01_openhands-v22-empty-content-normalization.md"
    )
    if (
        head != upstream
        or len(head) != 40
        or hash_bytes(v33_audit.read_bytes()) != _V33_AUDIT_FILE_SHA256
        or hash_bytes(v36_audit.read_bytes()) != _V36_AUDIT_FILE_SHA256
        or hash_bytes(root_cause.read_bytes()) != _V36_ROOT_CAUSE_FILE_SHA256
        or hash_bytes(v37_stop.read_bytes()) != _V37_STOP_AUDIT_FILE_SHA256
        or hash_bytes(v38_failure.read_bytes()) != _V38_FAILURE_AUDIT_FILE_SHA256
        or hash_bytes(v39_failure.read_bytes()) != _V39_FAILURE_AUDIT_FILE_SHA256
        or hash_bytes(v41_failure.read_bytes()) != _V41_FAILURE_AUDIT_FILE_SHA256
        or hash_bytes(v46_result.read_bytes()) != _V46_RESULT_AUDIT_FILE_SHA256
        or hash_bytes(v22_protocol.read_bytes()) != _V22_PROTOCOL_AUDIT_SHA256
    ):
        raise ConfigurationError("OpenHands v47 canary requires clean merged origin/main")
    return head


def _safe_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ConfigurationError(f"OpenHands v47 {label} root is unsafe")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ConfigurationError(f"OpenHands v47 {label} root is unavailable")
    return resolved


def _safe_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError(f"unsafe OpenHands v47 input: {path.name}")
    resolved = path.resolve(strict=True)
    if not 0 < resolved.stat().st_size <= _MAX_JSON_BYTES:
        raise ConfigurationError(f"oversized OpenHands v47 input: {resolved.name}")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    resolved = _safe_file(path)
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"malformed OpenHands v47 JSON input: {resolved.name}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"OpenHands v47 JSON input is not an object: {resolved.name}")
    return value


def _validated_content_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(value)
    observed = result.pop(field, None)
    if not isinstance(observed, str) or content_hash(result) != observed:
        raise ConfigurationError(f"OpenHands v47 {field} identity changed")
    return {**result, field: observed}


def _new_output(path: Path) -> Path:
    if path.exists() or path.is_symlink():
        raise ConfigurationError("OpenHands v47 output must not already exist")
    path.mkdir(parents=True, mode=0o700)
    return path.resolve(strict=True)


def _atomic_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for value in values:
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")))
                stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _seal_report(value: dict[str, Any]) -> dict[str, Any]:
    base = copy.deepcopy(value)
    base.pop("report_hash", None)
    return {**base, "report_hash": content_hash(base)}


def _write_report(root: Path, value: dict[str, Any]) -> None:
    atomic_dump_json(root / "canary-progress.json", _seal_report(value))


def _stop(
    root: Path,
    base_report: dict[str, Any],
    attempts: list[dict[str, Any]],
    *,
    status: str,
    reason: str,
) -> dict[str, Any]:
    accounting = _observed_provider_accounting(root, attempts)
    training_consumed = accounting["provider_episode_count"] > 0
    final = _seal_report(
        {
            **base_report,
            "status": status,
            "attempts": attempts,
            "canary_passed": False,
            "canary_trajectory_count": sum(
                int(item.get("trajectory_receipt") is not None) for item in attempts
            ),
            "exact_64k_trajectory_count": sum(
                int(item.get("token_receipt") is not None) for item in attempts
            ),
            "formal_collection_allowed": False,
            "training_task_disposition": (
                "replace_after_failed_canary"
                if training_consumed
                else "not_consumed_pre_provider_stop"
            ),
            "formal_training_schedule_requires_replacement": training_consumed,
            **accounting,
            "failure_reason": reason,
        }
    )
    atomic_dump_json(root / "canary-progress.json", final)
    atomic_dump_json(root / "canary-report.json", final)
    return final


def _observed_provider_accounting(root: Path, attempts: list[dict[str, Any]]) -> dict[str, int]:
    call_count = 0
    episode_count = 0
    runs = root / "runs"
    if runs.is_dir() and not runs.is_symlink():
        for path in sorted(runs.glob("*/artifacts/openhands_sdk/accounting.json")):
            accounting = ExternalAgentAccounting.model_validate(_load_json(path))
            observed_calls = accounting.model_call_count
            if isinstance(observed_calls, bool) or not isinstance(observed_calls, int):
                raise ConfigurationError("OpenHands v47 provider call accounting is missing")
            call_count += observed_calls
            episode_count += 1
    if episode_count == 0:
        receipts = [
            item["protocol_receipt"]
            for item in attempts
            if isinstance(item.get("protocol_receipt"), dict)
        ]
        call_count = sum(int(item["provider_call_count"]) for item in receipts)
        episode_count = len(receipts)
    return {"provider_episode_count": episode_count, "provider_call_count": call_count}


def main() -> int:
    report = collect(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "canary_passed": report["canary_passed"],
                "formal_collection_allowed": report["formal_collection_allowed"],
                "formal_collection_started": report["formal_collection_started"],
                "training_started": report["training_started"],
                "provider_episode_count": report["provider_episode_count"],
                "provider_call_count": report["provider_call_count"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["formal_collection_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
