# DeepSeek Harness v182 task-free build diagnostic authorization

Date: 2026-09-06

## Decision

Authorize one invocation of identity
`deepseek-harness-hwe-v182-bounded-open-build-diagnostic-v1` after this implementation is merged
and a newer `main` run passes all eight workflow classes. This is a zero-provider, task-free build
diagnostic, not a qualification, canary, trajectory collection, benchmark run, or training job.

V181 froze v180 as `offline_final_image_build_nonzero`: the corrected `/data2` DinD route and
immutable local builder probe passed, but the inherited quiet build helper discarded the output
needed to classify the final Verilator image failure. V181 also found that the normal cleanup path
could not traverse root-owned DinD backing and therefore failed to write a terminal report. V182
addresses only those observability and cleanup-controller defects. It does not retry or continue
v180.

## Inputs and isolation

V182 binds the exact v180 Dockerfile, the completed v178 dependency-only builder archive, the
accepted open-tool image, the Verilator 5.008 source archive, the ripgrep 15.2.0 archive, and the
Docker 23.0.6 DinD image. All archives and images must already be local and match their immutable
hashes or IDs. The build uses `--network none`, `--pull=false`, and plain progress output. Registry
access, downloads, partial archives, VPN/proxy changes, Docker-daemon changes, host EDA fallback,
and `LocalRuntime` are forbidden.

The fresh DinD data and socket backing lives only under
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v182`. The outer daemon has `network=none` and no
host Docker socket or provider/proxy environment. V182 imports only the accepted open-tool image
and the dependency-only builder archive. It does not inspect or import an HWE task image, read task
metadata, prepare PR-1816 source, run either verifier route, create a model process, or expose a
provider client.

## Bounded diagnostic and cleanup

The controller captures at most 16 MiB combined build output for at most 3,600 seconds and kills
the client process group on timeout or overflow. Before retaining hashes, it compares the capture
against active credential/proxy values and secret-like markers. A match persists only category
`sensitive_output`, byte counts, and empty-stream hash sentinels. Otherwise the receipt retains
only one fixed category, return status, boundedness flags, byte counts, and SHA-256 values. Raw
output, command arguments, environment names, environment values, and exceptions are never
persisted.

After every post-output outcome, v182 removes its outer containers, runs an inspected cleanup
helper over only the exact backing parent, removes both named volumes, and removes scratch. The
helper uses the immutable accepted open-tool image, `network=none`, a read-only root, one writable
bind, user `0:0`, cap-drop `ALL`, only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`, no-new-privileges,
private IPC, and fixed CPU, memory, PID, time, and output bounds. Its sole purpose is to delete the
root-owned DinD backing contents and restore the parent to the invoking UID/GID. The controller
must write `build-diagnostic.json`, `cleanup.json`, and a terminal `zero-provider-report.json` even
when an earlier controller action or cleanup step fails.

Run it exactly once from clean merged `main`:

```bash
VERIGYM_RUN_DEEPSEEK_HARNESS_V182_BOUNDED_OPEN_BUILD=1 \
  python scripts/launch_hwe_deepseek_harness_v182_bounded_open_build.py \
  --post-merge-main-run-id <successful-v182-main-run-id>
```

Any result requires an independent v183 audit. Only that audit may authorize a fresh repaired
qualification identity. PR-1816 remains task- and provider-unconsumed before v182, and the
research-only DeepSeek canary remains unauthorized. The following stay false:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`;
- `production_training_ready=false`.
