# DeepSeek Harness v168 real-config initialization diagnostic authorization

Date: 2026-09-05

Status: **one real-config, zero-request diagnostic authorized only after merge and green
post-merge `main`**.

## Decision and immutable inputs

Authorize exactly one execution of
`deepseek-harness-hwe-v168-real-config-initialize-diagnostic-v1`. V168 is the narrow diagnostic
allowed by the v167 audit of the frozen v166 pre-provider failure. It is not a retry of v166 and
does not authorize a task, verifier, provider request, trajectory, collection, or training run.

- Manifest SHA-256: `24bfdc937718e12d60e4590d01d22d3241e8cf8a9da43eea9f7302adab2ebaa9`
- Manifest canonical hash: `cc0f1afa54416f3806a13c7afe963559c792cbf723748c47fb85c5635be04fdb`
- Runner SHA-256: `46c81870b96f5f213620b00e2eb2a9bf7338680882937779c2da89ef3e64047e`
- Launcher SHA-256: `2ee17360279c3e29260b7c199c9a962ba552f2619167247b28f867a02dba478e`
- Structured-process module SHA-256:
  `710269e4c3be6cf084fbf7f744f14496ceffd2325f313380cde8e866ab6cfa24`
- v167 audit commit: `41bc81a7014a3ad7f245b5ece19d0fd8d763143c`
- v167 audit merge: `88edac0ac081aedc40f9b845a2f6f7efefd0f295`
- v167 post-merge `main`: `33973532777`, eight of eight job classes passed

Execution additionally requires the exact merge commit containing this authorization to pass all
eight post-merge `main` job classes. The runner rejects a non-`main`, dirty, or non-up-to-date
checkout and records that run ID in atomic progress.

## Diagnostic and credential boundary

V168 revalidates the complete immutable v164 and v166 evidence trees, their canonical terminal
reports and decisive receipts, both implementations and authorizations, the v165 and v167 audits,
and the pinned helper/process modules before output creation. V164 must remain a passed synthetic
initialization diagnosis. V166 must remain a cleaned pre-provider infrastructure failure with
marker `not_started`, zero episodes, zero calls, zero tokens, no task consumption, and no admitted
data.

The launcher derives its blocked set from the frozen twelve-name provider boundary plus both
Docker endpoint names. It selects allowed names before reading any blocked value, then reads and
copies only `VERIGYM_DEEPSEEK_API_KEY` and `VERIGYM_DEEPSEEK_API_BASE_URL`. The child requires
those two values to be nonempty and distinct and rejects every provider alias or ambient Docker
endpoint. Values are never printed, persisted, or hashed.

Harness receives the exact v166 initialize-mode prompt, session identity, controller settings,
and nested Unix endpoint. It may only initialize: the task prompt is empty and the runner has no
task, verifier, candidate, or provider-run surface. A provider request marker is a hard
infrastructure failure. All private session and broker files are compared in memory with both
provider values and removed before publication; every published evidence file is checked the same
way. The receipt retains only an allowlisted structured helper category, booleans, counts, and
non-secret hashes. Raw exceptions, stderr, helper output, and credential values are prohibited.

A direct controller probe first rechecks the immutable image, explicit endpoint, exact mounts,
non-root and read-only execution, capability removal, no-new-privileges, private namespaces,
resource limits, bounded tmpfs, dedicated bridge, and absence of all provider names from that
probe container.

## Docker and cleanup boundary

V168 may reopen the exact retained `verigym-deepseek-harness-v158-dind-data` volume once, bringing
its cumulative reopen count from three to four. It uses a fresh v168 socket volume and fresh
`/data2` socket, control, runtime, output, and receipt paths. It does not pull, import, rebuild,
substitute, access `.partial` images, run a benchmark task, inspect unrelated Docker resources,
change Docker daemon configuration, or modify VPN/proxy state. Only the outer DinD and inner
diagnostic controller use `verigym-hwe-net`; no task or verifier container is created.

Cleanup removes only v168-owned containers, the inner bridge, socket volume, and private controller
artifacts. The retained v158 data volume remains intact. Any evidence, security, marker,
value-scan, output-bound, infrastructure, or cleanup failure stops fail closed. The v168 identity
is consumed regardless of outcome and cannot authorize its own successor.

Run exactly once after merge and the new green post-merge gate:

```text
VERIGYM_RUN_DEEPSEEK_HARNESS_V168_REAL_CONFIG_INITIALIZE_DIAGNOSTIC=1 \
python scripts/launch_hwe_deepseek_harness_v168_real_config_initialize_diagnostic.py \
  --post-merge-main-run-id <green-main-run-id>
```

`formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready` remain false. The result is pending an
independent v169 audit. V168 cannot itself authorize a provider retry, formal collection, SFT, GPU
work, benchmark scoring, held-out access, or production training.
