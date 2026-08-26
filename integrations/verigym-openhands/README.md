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

The HWE backend uses the SDK's Stop Hook extension point to correct OpenHands 1.42.1's
content-only completion behavior. The broker's successful typed `finish` is the only completion
authority. Before that point, the first content-only stop is denied and receives one canonical
same-session recovery message; a second premature stop fails closed without resetting the
workspace or retrying the episode. Recovered transcripts use the v2 trajectory/decision/dataset
formats. They retain and hash-bind the premature assistant message and recovery feedback as
loss-masked context. Existing v1 trajectories and hashes remain valid and unchanged.

This integration establishes the collection and export path. A bounded development run remains a
pilot and is not a benchmark score or a production-training-readiness claim.

`scripts/run_cva6_hwe_openhands_recovery_diagnostic.py` freezes a distinct v2 agent identity and
runs exactly one no-retry PR-2032 regression episode. It hash-binds the prior v1 missing-`finish`
failure and accepts the recovery regression only when the same OpenHands session consumes its one
recovery allowance and subsequently reaches broker-authoritative typed `finish`. Verifier
correctness is reported separately. Even a verifier-passed diagnostic trajectory is not admitted
to a dataset automatically. A relaunch after a pre-model infrastructure failure must use a new
frozen attempt identity and hash-bind evidence of zero model calls and zero workspace changes.

The v3 required-tool follow-up used a local `LLM` subclass through the SDK's public completion
methods to send `tool_choice="required"` on every sync and async chat request. Its bounded real
PR-2032 diagnostic proved the provider accepted that parameter and eliminated content-only stops,
but DeepSeek made 200 accepted tools without choosing `finish`; the broker rejected decision 201
at its frozen limit. No patch, verifier result, trajectory, or dataset row was produced.

The v4 adaptive diagnostic kept ordinary turns at `tool_choice=auto` and attempted to force the
concrete `finish` function after trusted Stop-hook feedback. Its real run exercised one recovery,
but its exact-whole-message detector did not account for the SDK merging adjacent plain-user
messages. The next response was content-only again, so the run failed closed with 13 accepted
tools, no patch, and no trajectory.

The v5 diagnostic recognized recovery only when the latest user message's final independent content
block exactly equaled the canonical feedback. Its real run exercised one recovery but still produced
a second content-only stop: the Stop-hook receipt proved that recovery occurred, but the effective
agent message shape remained an unreliable policy boundary. It made 14 accepted read/shell calls,
no patch, no `finish`, and no trajectory.

The v6 diagnostic bound named `finish` to the Stop hook's private recovery receipt rather than a
message layout. Its real run exercised one recovery, but the provider returned further ordinary
tools instead of reaching broker-authoritative `finish`; after 69 accepted actions the invalid run
was interrupted to prevent further API consumption. It made no patch or trajectory. The sealed v6
report contains one `InterruptEvent`, so it is failure evidence rather than an ordinary completed
sample.

The v7 diagnostic added response validation. Its real run made 26 ordinary actions, exercised one
recovery, and rejected the provider's non-finish response before broker dispatch with
forced-request count 1 and validated-finish count 0. OpenHands wrapped the local violation in
`ConversationRunError`; the v7 evidence finalizer checked only the outer exception and therefore
reported an infrastructure error without the normal broker summary. No patch or trajectory was
produced.

`scripts/run_cva6_hwe_openhands_tool_choice_diagnostic.py` now freezes the distinct v8 diagnostic.
Ordinary turns remain `auto`; after the Stop hook atomically writes its private, validated recovery
receipt, the next request selects the concrete `finish` function. The local LLM subclass then
accepts only a provider response containing exactly one `finish` call before OpenHands can dispatch
anything to the broker. It records separate forced-request and validated-finish counters, rejects
interrupted evidence, recognizes the controlled violation through OpenHands' bounded causal
exception chain, and fails closed on any other response. The run binds the sealed v7 failure and
its exact trace hash.
It does not monkeypatch the SDK or synthesize an action. Verifier correctness and trajectory
eligibility remain separate, and no diagnostic result is admitted to a dataset.

## Five-task HWE collection pilot

`scripts/collect_cva6_hwe_openhands_pilot.py` is the opt-in multi-task collection entry point. It
reuses the sealed verifier-passed PR-2944 trajectory and makes one no-retry OpenHands attempt for
PR-2032, PR-2549, PR-2248, and PR-2282, all from the existing frozen CVA6 training split. The
runner stops on infrastructure-invalid or exact-64K failures. Ordinary verifier rejection remains
a valid negative outcome and never creates an SFT row.

The runner requires `VERIGYM_RUN_OPENHANDS_HWE_PILOT=1`, the existing DeepSeek endpoint variable
names, a short `VERIGYM_OPENHANDS_BROKER_ROOT`, and an explicit
`VERIGYM_OPENHANDS_MCP_PYTHONPATH`. It writes only to a new experiment directory. Full runs and
datasets remain local; only sanitized reports and hashes belong in Git.
