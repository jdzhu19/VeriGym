"""HWE-oriented native-shell collection contracts.

This package is deliberately separate from the strict repository-tool v1/v2 path.  Importing it
does not alter the historical repository action registry or transcript identities.
"""

from verigym.hwe.coact import (
    COACT_DATASET_FORMAT_ID,
    COACT_EXAMPLE_FORMAT_ID,
    COACT_FORMAT_ID,
    COACT_MAX_LENGTH,
    build_coact_checkpoint_lock,
    build_coact_dataset_manifest,
    compress_hwe_trajectory,
    seal_coact_example,
)
from verigym.hwe.history_masking import (
    HWE_ACTION_CONDITIONED_DATASET_FORMAT,
    HWE_ACTION_CONDITIONED_SFT_FORMAT,
    HWE_HISTORY_MASKING_POLICY_ID,
    HWE_SELECTED_HISTORY_WINDOW,
    HweHistoryMaskingPolicy,
    build_hwe_action_conditioned_dataset_manifest,
    derive_hwe_masked_history_views,
    materialize_hwe_action_conditioned_examples,
    validate_hwe_action_conditioned_example,
)
from verigym.hwe.image_lock import HweAgentImageLock
from verigym.hwe.nap import (
    NAP_SIMILARITY_THRESHOLD,
    AnchorNapValidator,
    canonical_action_hash,
    typed_action_similarity,
)
from verigym.hwe.observation import (
    HweObservationCompactor,
    HweObservationResult,
    TiktokenO200kCounter,
)
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_ID,
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_CURRENT_COLLECTION_PROFILE_ID,
    HWE_OBSERVATION_POLICY_ID,
    HWE_OBSERVATION_POLICY_V2_ID,
    HWE_TOOL_CONTRACT_ID,
    HWE_TOOL_CONTRACT_V2_ID,
    HweCollectionProfile,
    canonical_hwe_action_json,
    hwe_tool_contract_hash,
    hwe_tool_definitions,
    resolve_hwe_collection_profile,
)
from verigym.hwe.trajectory import (
    HweEpisodeBudget,
    build_hwe_teacher_transcript,
    validate_hwe_teacher_transcript,
)

__all__ = [
    "HWE_ACTION_CONDITIONED_DATASET_FORMAT",
    "HWE_ACTION_CONDITIONED_SFT_FORMAT",
    "COACT_DATASET_FORMAT_ID",
    "COACT_EXAMPLE_FORMAT_ID",
    "COACT_FORMAT_ID",
    "COACT_MAX_LENGTH",
    "HWE_COLLECTION_PROFILE_ID",
    "HWE_COLLECTION_PROFILE_V2_ID",
    "HWE_CURRENT_COLLECTION_PROFILE_ID",
    "HWE_OBSERVATION_POLICY_ID",
    "HWE_OBSERVATION_POLICY_V2_ID",
    "HWE_TOOL_CONTRACT_ID",
    "HWE_TOOL_CONTRACT_V2_ID",
    "HWE_HISTORY_MASKING_POLICY_ID",
    "HWE_SELECTED_HISTORY_WINDOW",
    "HweAgentImageLock",
    "AnchorNapValidator",
    "HweCollectionProfile",
    "HweEpisodeBudget",
    "HweHistoryMaskingPolicy",
    "HweObservationCompactor",
    "HweObservationResult",
    "TiktokenO200kCounter",
    "NAP_SIMILARITY_THRESHOLD",
    "build_coact_checkpoint_lock",
    "build_coact_dataset_manifest",
    "build_hwe_teacher_transcript",
    "build_hwe_action_conditioned_dataset_manifest",
    "canonical_hwe_action_json",
    "canonical_action_hash",
    "compress_hwe_trajectory",
    "hwe_tool_contract_hash",
    "hwe_tool_definitions",
    "derive_hwe_masked_history_views",
    "materialize_hwe_action_conditioned_examples",
    "resolve_hwe_collection_profile",
    "seal_coact_example",
    "typed_action_similarity",
    "validate_hwe_teacher_transcript",
    "validate_hwe_action_conditioned_example",
]
