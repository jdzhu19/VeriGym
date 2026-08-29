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

The frozen OpenHands base environment retains `tiktoken==0.11.0`, which satisfies
`litellm==1.93.0`. HWE exact-token collection prepends a separate `tiktoken==0.7.0` target
overlay at process launch. Do not ask pip to resolve both versions into one environment:
LiteLLM declares `tiktoken>=0.8.0`, while the HWE tokenizer receipt intentionally remains bound
to 0.7.0. CI reproduces the same base-plus-overlay layout and checks both identities before any
credential-free tests run.

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
skills, dynamic context, foreign events, unsupported rejected calls, incomplete episodes, and
secrets.

The HWE adapter counts provider attempts at the LLM transport boundary. That counter is independent
of broker decision steps because one provider response may contain sibling tool calls. The frozen
request budget is enforced before dispatch, while broker action counts remain a separate receipt.
Aggregate input/output token usage is persisted without model content.

OpenHands command hooks inherit the parent locale through SDK 1.42.1. The adapter temporarily
freezes the agent-loop subprocess locale to portable POSIX `C`, preventing an unavailable host
`C.UTF-8` locale from adding non-protocol stderr to an otherwise valid Stop-hook receipt. The prior
stderr-empty fail-closed trajectory rule remains unchanged. Exact HWE v2 arguments may retain
container-local `/tmp`, the profile's frozen ephemeral scope; `/home`, `/data`, `/hpc`, and Windows
absolute host paths remain ineligible.

The v3 exact trajectory format makes one narrow exception to whole-episode rejection: broker
rejections whose only code is `invalid_arguments` remain in the exact model-visible context, but
their complete assistant decisions are marked `supervised_target=false` and never become target
rows. Later accepted decisions retain those failed calls and error observations in their masked
input prefix. Unknown tools, other rejection codes, missing error flags, causal drift, and
verifier-failed episodes remain ineligible. This matches the existing DeepSeek Harness v3
decision-only masking rule without weakening broker execution policy.

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

The bounded real v8 run made 12 ordinary actions, exercised one recovery, recorded
forced-request count 1, and rejected the provider response with validated-finish count 0. It ended
as the infrastructure-valid model failure `openhands_hwe_recovery_tool_choice_violation`, with no
interrupt, further broker action, patch, finish, trajectory, or dataset row. This closes the unsafe
continuation and misclassification defects, but it does not establish successful OpenHands
termination for this model. Production collection remains blocked until the provider/model returns
the requested typed `finish` under the actual agent history.

The first Responses-recovery v9 attempt stopped before model initialization because its launch
environment omitted the `verigym-deepseek-harness` integration source. It was sealed as
`hwe_broker_unavailable` with zero model calls, zero tools, zero workspace changes, and no recovery.

The v10 attempt crossed model initialization and completed 21 ordinary OpenHands actions and
observations, but its receipt-bound Responses request ended in an HTTP 400 before a typed finish.
The sealed report contains no raw provider content, patch, or trajectory. A bounded provider probe
reproduced the relevant protocol rejection: OpenHands SDK 1.42.1 serializes each text block in one
tool message as a separate `function_call_output`, while the provider permits only one output for
each `call_id`.

The v11 attempt made 14 ordinary model/tool actions, exercised the one recovery, and coalesced 14
duplicate output blocks. The Responses request therefore crossed the v10 HTTP 400 boundary, but
the converted response was not exactly one typed `finish`. It was sealed as the
infrastructure-valid model failure `openhands_hwe_recovery_tool_choice_violation`, before any later
broker dispatch, with no workspace mutation, finish, trajectory, or dataset row.

The v12 attempt hash-bound the v9, v10, and v11 outcomes. Ordinary actions still used Chat
Completions with the full six-tool contract. Only after the trusted recovery receipt existed, the
adapter converted the same complete history and all six tools through OpenHands' public Responses
serializer and sent a Responses API named `finish` choice. OpenHands SDK 1.42.1 currently resets Responses
`tool_choice` to `auto`; the v9 policy subclass rebinds the adapter-owned named choice after
serialization without changing the installed SDK. The adapter also joins adjacent text outputs
belonging to one tool message into exactly one output for that call ID. It rejects non-text outputs
and non-adjacent call-ID reuse, and records the number of joins; v11 acceptance requires that the
repair was exercised. The provider must return exactly one typed `finish` before broker dispatch.
The v12 adapter also recorded a content-free response-shape receipt containing only bounded output
types, allowed tool names, and raw/converted counts. Unexpected names are hashed, and model text is
never retained. Its real run reached typed `finish`, made four patches, and passed both hidden
verifier tests. Two earlier shell decisions had been rejected as `invalid_arguments`, however, so
the then-current all-or-nothing action policy withheld the trajectory. The v12 report also
incorrectly labeled the otherwise complete direct-finish evidence as infrastructure-invalid
because it required a recovery response-shape receipt even though no recovery request occurred.
Both defects are fixed in later source: the response-shape receipt is conditional on a forced
request, and exact v3 trajectories retain those failed decisions only as unsupervised context.

The v13 qualification bound the complete v12 report and trace, but its real recovery response was
one structurally valid `read_file`, not the requested `finish`. The guard rejected it before broker
dispatch. The v14 policy therefore follows the Stop-hook's actual instruction: its single
receipt-bound Responses request uses `tool_choice="required"`, accepts exactly one known six-tool
call with no prose, dispatches that call through the same broker, and returns subsequent turns to
ordinary Chat Completions. Missing, unknown, multiple, or text-mixed calls still fail closed.

The real v14 run validated and executed one recovered `read_file`, proving that continued recovery
path. The model later attempted another content-only stop after the one recovery allowance was
spent, made no workspace mutation, and never called typed `finish`; it therefore failed as
`openhands_hwe_missing_finish`, with no eligible trajectory or dataset row. This is now a model
completion outcome rather than an OpenHands/Responses transport defect. The runner permits no
provider or episode retry and never admits a diagnostic result to a dataset automatically.

The v15 adapter added one explicit same-session SDK continuation after that exact validated,
non-terminal recovery state. Its real PR-2032 run continued for 20 typed actions and made five
patch attempts, but a raw host path appeared in a provider tool argument and was rejected before
broker dispatch. The v16 provider schema therefore applies the workspace boundary to every string
field, not only `path` and `cwd`, and records only the tool name, top-level field name, and violation
kind. Its real run crossed that boundary with no path violation. The recovery and adapter
continuation were both exercised, but the continuation was still an ordinary `auto` request and
the model again returned prose instead of a typed tool, so no trajectory was admitted.

The distinct v17 diagnostic arms exactly one adapter-continuation request only after the validated
recovery state. That request uses the Responses serializer with `tool_choice="required"`, requires
exactly one of the six canonical tools with no prose, reuses the v16 path contract, and then returns
to ordinary Chat Completions. Recovery and continuation response-shape receipts remain separate,
and provider accounting is read from the LLM object actually owned by the OpenHands conversation.
The installed OpenHands SDK is not modified, no action is synthesized, and the continuation budget
remains one.

The real v17 PR-2032 diagnostic passed those adapter and protocol gates exactly once: one recovery,
one same-session SDK continuation, one `tool_choice="required"` request, and one validated
`read_file` tool. It made 16 model calls and 14 broker tool calls, with no path/schema violation,
patch, or typed `finish`. The run therefore ended as the infrastructure-valid model failure
`openhands_hwe_missing_finish`; it exported no trajectory and did not enter a dataset. Its sealed
report hash is `440b47085983bd204713c5c732905eef67ff8d94d0053cadd9a2eb5cb57bd423`. This closes
the current adapter boundary, but it does not qualify PR-2032 or justify a retry, synthesized
`finish`, benchmark claim, or production-training claim. See the
[v17 audit](../../docs/audits/2026-08-28_openhands-hwe-typed-continuation-v17.md) for the complete
sanitized counts and frozen identities.

## v19 required-tool collection protocol

The independent v19 policy uses `tool_choice=required` for every active provider request and
accepts exactly one canonical call from the six metadata-free, workspace-relative HWE tools. One
provider content-only response may enter the same OpenHands session so the trusted Stop hook can
retain it and add the canonical environment recovery feedback. The content and feedback remain
complete model input but are loss-masked; only later canonical tool decisions are supervised. A
second content-only response, prose mixed with tools, multiple or foreign tools, pseudo-`finish`,
counter drift, or unavailable token accounting fails closed before broker dispatch.

v19 freezes 64 provider calls, 1,000,000 cumulative provider tokens, 65,536 context tokens, 2,048
output tokens, temperature zero, and no provider or episode retries. A response crossing the
cumulative token cap remains in SDK accounting but cannot enter OpenHands or the broker. The
protocol receipt records required requests, canonical tools, content-only responses, recovery
counts, token usage, call usage, and broker decisions. Separate campaign results record actual
verifier pass, protocol validity, trajectory eligibility, infrastructure validity, security
validity, and SFT admission without changing `ScoreCard.resolved`.

The frozen v19 public qualification order is CVA6 PR-2330, 3226, 2844, 3231, 2989, 1482, and 3059,
ordered by changed lines and PR number. Qualification is zero-model base-FAIL/reference-PASS and
must produce five tasks before any provider canary is allowed. It excludes every historical
attempt, existing train/validation task, PR-2170, and all six held-out tasks. The source implements
the 3-training/2-validation reserve assignment and fail-closed canary/collection capacity gates;
it does not implicitly load a corpus, invoke a model, or authorize training.

The sealed PR-2469 scorecard regression is intentionally classification-only: its actual hidden
verifier result is one of one passing even though top-level `resolved` is false because the agent
protocol and trajectory gate failed. v19 therefore classifies it as verifier-pass and
trajectory-ineligible, without reconstructing, importing, rerunning, or relabeling the historical
episode.

The first v19 public-task stage stopped before task execution. The controlled image downloader's
effective process unexpectedly exposed an unauthenticated TCP Docker API on the dedicated bridge;
the container and scratch state were removed, zero images were imported, and qualification did not
start. The runner now requires a Unix-only nested daemon and validates its effective arguments,
but the stopped stage is not retried and no reserve split or canary contract exists. See the
[qualification audit](../../docs/audits/2026-08-29_openhands-v19-public-qualification-stopped.md).

The separately authorized v20 daemonless prewarm preflight does not retry or modify that v19
stage. It bootstraps the SHA-256-pinned official `crane` v0.22.0 release in a non-privileged,
non-root container on `verigym-hwe-net`, then runs `crane version` with `network=none` and one
registered non-candidate digest probe on the dedicated bridge. Every container has a read-only
root, cap-drop `ALL`, no-new-privileges, bounded resources, no ports, no Docker socket, and only one
scratch mount. Its initial authorization explicitly forbids candidate downloads, image loading,
qualification and provider calls. See the
[v20 authorization audit](../../docs/audits/2026-08-29_openhands-v20-daemonless-prewarm-authorization.md).

That authorized preflight ran once and stopped fail closed inside the controlled tool-bootstrap
command. Its temporary container and partial tool directory were removed; no candidate image,
qualification task, provider call, or held-out task was touched. The v20 identity is sealed and no
candidate-transfer authorization exists. See the
[v20 stopped audit](../../docs/audits/2026-08-29_openhands-v20-daemonless-prewarm-stopped.md).

The v21 successor follows the producer's official release workflow: it understands the Sigstore
bundle wrapper, pins `slsa-verifier` v2.7.1, cryptographically verifies the archive provenance, and
records bounded content-free stage receipts. Its single authorized preflight proved that all public
inputs and structural checks passed, then stopped before the verifier process started because an
unqualified executable name was absent from the restricted `PATH`. See the
[v21 repair authorization](../../docs/audits/2026-08-29_openhands-v21-daemonless-bootstrap-fix-authorization.md)
and [v21 stopped audit](../../docs/audits/2026-08-29_openhands-v21-daemonless-prewarm-stopped.md).

The distinct v22 authorization resolves that exact process-launch defect without adding the
writable download directory to `PATH`: it validates and invokes the fully qualified registered
verifier file, binds the path into both progress and final receipts, and adds a restricted-`PATH`
regression. It still authorizes only one no-candidate preflight after merge. See the
[v22 path-fix authorization](../../docs/audits/2026-08-29_openhands-v22-daemonless-path-fix-authorization.md).
That preflight proved the SLSA and absolute-path repair, then stopped at a separate version-output
assumption before the non-candidate registry probe. The identity is sealed; see the
[v22 stopped audit](../../docs/audits/2026-08-29_openhands-v22-daemonless-prewarm-stopped.md).

The v23 successor independently registers the exact `crane version` bytes for the pinned binary
instead of deriving them from the release tag. It retains the v22 SLSA and absolute-path controls,
uses a new cache, and still authorizes only one no-candidate preflight after merge. See the
[v23 version-contract authorization](../../docs/audits/2026-08-29_openhands-v23-version-contract-fix-authorization.md).
That preflight passed the registered version smoke and stopped at the final public registry probe
because its Debian slim execution image had no CA trust store. See the
[v23 stopped audit](../../docs/audits/2026-08-29_openhands-v23-daemonless-prewarm-stopped.md).

The v24 successor uses the already locked CA-bearing Python slim image for crane execution and adds
a `network=none` CA-bundle precheck before any crane command. It neither disables TLS nor installs
packages at runtime. See the
[v24 CA-precheck authorization](../../docs/audits/2026-08-29_openhands-v24-ca-precheck-fix-authorization.md).

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
