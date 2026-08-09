"""Framework-neutral external training reference for VeriGym."""

from .campaign import (
    CampaignStageSpec,
    TrainingCampaignSpec,
    load_campaign_spec,
    run_training_campaign,
)
from .heldout import (
    build_public_input_record,
    freeze_heldout_evaluation,
    summarize_heldout_results,
)
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
    "ModelSnapshotIdentity",
    "OnlineRewardResult",
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
    "freeze_heldout_evaluation",
    "inspect_model_snapshot",
    "load_campaign_spec",
    "load_training_config",
    "prepare_training_bundle",
    "register_checkpoint",
    "register_training_policy_version",
    "resolve_model_root",
    "run_training_campaign",
    "summarize_heldout_results",
    "validate_training_bundle",
]
