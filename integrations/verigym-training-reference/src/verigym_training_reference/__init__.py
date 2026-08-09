"""Framework-neutral external training reference for VeriGym."""

from .pipeline import (
    exclusion_counts,
    inspect_model_snapshot,
    load_training_config,
    prepare_training_bundle,
    register_checkpoint,
    resolve_model_root,
    validate_training_bundle,
)
from .reward_oracle import TrainingRewardOracle
from .schemas import (
    ModelSnapshotIdentity,
    OnlineRewardResult,
    SftMessage,
    TrainingReferenceBundleManifest,
    TrainingReferenceConfig,
    VerifiedSftDatasetManifest,
    VerifiedSftExample,
)
from .trl_adapter import TrlRewardAdapter, build_trl_dataset_rows

__all__ = [
    "ModelSnapshotIdentity",
    "OnlineRewardResult",
    "SftMessage",
    "TrainingReferenceBundleManifest",
    "TrainingReferenceConfig",
    "TrainingRewardOracle",
    "TrlRewardAdapter",
    "VerifiedSftDatasetManifest",
    "VerifiedSftExample",
    "build_trl_dataset_rows",
    "exclusion_counts",
    "inspect_model_snapshot",
    "load_training_config",
    "prepare_training_bundle",
    "register_checkpoint",
    "resolve_model_root",
    "validate_training_bundle",
]
