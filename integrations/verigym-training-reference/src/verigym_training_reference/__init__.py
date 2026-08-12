"""Framework-neutral external training reference for VeriGym."""

from .campaign import (
    CampaignStageSpec,
    TrainingCampaignSpec,
    load_campaign_spec,
    run_training_campaign,
)
from .heldout import (
    RepositoryHeldoutFreezeManifest,
    RepositoryHeldoutRequest,
    build_public_input_record,
    freeze_heldout_evaluation,
    freeze_repository_heldout,
    load_repository_heldout_freeze,
    summarize_heldout_results,
)
from .native_runtime import (
    GpuHealthSample,
    NativeGpuToolchain,
    NativeTrainingRuntimeManifest,
    parse_visible_devices,
    replace_topology_overrides,
    seal_runtime_manifest,
    select_gpu_devices,
    topology_overrides,
    validate_runtime_manifest,
)
from .online_policy import export_online_policy_version
from .pipeline import (
    exclusion_counts,
    inspect_model_snapshot,
    load_training_config,
    prepare_training_bundle,
    register_checkpoint,
    resolve_model_root,
    validate_training_bundle,
)
from .policy_versions import register_training_policy_version
from .reward_oracle import TrainingRewardOracle
from .schemas import (
    ModelSnapshotIdentity,
    OnlineRewardResult,
    SftMessage,
    TrainingPolicyVersionManifest,
    TrainingReferenceBundleManifest,
    TrainingReferenceConfig,
    VerifiedSftDatasetManifest,
    VerifiedSftExample,
)
from .trl_adapter import TrlRewardAdapter, build_trl_dataset_rows

__all__ = [
    "CampaignStageSpec",
    "GpuHealthSample",
    "ModelSnapshotIdentity",
    "NativeGpuToolchain",
    "NativeTrainingRuntimeManifest",
    "OnlineRewardResult",
    "RepositoryHeldoutFreezeManifest",
    "RepositoryHeldoutRequest",
    "SftMessage",
    "TrainingReferenceBundleManifest",
    "TrainingReferenceConfig",
    "TrainingCampaignSpec",
    "TrainingPolicyVersionManifest",
    "TrainingRewardOracle",
    "TrlRewardAdapter",
    "VerifiedSftDatasetManifest",
    "VerifiedSftExample",
    "build_trl_dataset_rows",
    "build_public_input_record",
    "exclusion_counts",
    "export_online_policy_version",
    "freeze_heldout_evaluation",
    "freeze_repository_heldout",
    "inspect_model_snapshot",
    "load_campaign_spec",
    "load_training_config",
    "load_repository_heldout_freeze",
    "prepare_training_bundle",
    "parse_visible_devices",
    "register_checkpoint",
    "register_training_policy_version",
    "resolve_model_root",
    "replace_topology_overrides",
    "run_training_campaign",
    "seal_runtime_manifest",
    "select_gpu_devices",
    "summarize_heldout_results",
    "topology_overrides",
    "validate_runtime_manifest",
    "validate_training_bundle",
]
