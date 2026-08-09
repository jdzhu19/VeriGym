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
    TrainingReferenceBundleManifest,
    TrainingReferenceConfig,
)
from .trl_adapter import TrlRewardAdapter, build_trl_dataset_rows

__all__ = [
    "ModelSnapshotIdentity",
    "OnlineRewardResult",
    "TrainingReferenceBundleManifest",
    "TrainingReferenceConfig",
    "TrainingRewardOracle",
    "TrlRewardAdapter",
    "build_trl_dataset_rows",
    "exclusion_counts",
    "inspect_model_snapshot",
    "load_training_config",
    "prepare_training_bundle",
    "register_checkpoint",
    "resolve_model_root",
    "validate_training_bundle",
]
