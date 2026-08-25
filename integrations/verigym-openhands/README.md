# verigym-openhands

Optional OpenHands SDK 1.42.1 inference harness for repository tasks. It exposes only the six
canonical VeriGym broker tools. OpenHands receives no repository mount, terminal, file editor,
Docker socket, hidden asset, reference solution, plugin, or skill.

The optional `hwe` extra registers `openhands-hwe-agent`. That backend retains the empty OpenHands
workspace but routes the frozen HWE native-shell six-tool contract through the existing isolated
DeepSeek broker. `shell` therefore runs only inside the task-keyed, networkless agent container;
it is not a host shell.

Real runs are opt in and require Python 3.12, `VERIGYM_OPENHANDS_BROKER_ROOT`, and the configured
model endpoint environment variables.

The development comparison is intentionally two samples, not a benchmark score. Freeze distinct
base and adapter policy manifests with `scripts/freeze_openhands_sft_agent_versions.py`, then run
`scripts/run_openhands_cva6_development_pilot.py` against the two frozen CVA6 validation tasks.
Both commands reject held-out/training split drift; the pilot stops on infrastructure-invalid
results and never retries an episode.

## Training trajectory capture

Both agent backends accept `campaign_role=training` with
`capture_training_transcript=true`. Capture is rejected for development, evaluation, and held-out
roles. The collector reconciles every OpenHands `ActionEvent` and `ObservationEvent` with the
broker-owned canonical arguments and compact-observation hash. It preserves the exact effective
OpenHands tool schemas, including SDK-added tool metadata, while excluding reasoning blocks,
skills, dynamic context, foreign events, rejected calls, incomplete episodes, and secrets.

The agent holds message content in memory until the ordinary verifier finishes. It writes
`training-trajectory.json` only when the candidate resolves and the infrastructure remains valid.
Unresolved or infrastructure-invalid episodes never become positive SFT records. The exported
trajectory can then be converted with `materialize_openhands_decisions` into tool-aware 64K
`messages + tools + target_message` rows. Every row contains exact tokenizer, chat-template,
input-ID, and loss-mask receipts; overlength rows fail instead of truncating. Dataset directories
are created with `write_openhands_decision_dataset` and are never overwritten.

This integration establishes the collection and export path. A bounded development run remains a
pilot and is not a benchmark score or a production-training-readiness claim.
