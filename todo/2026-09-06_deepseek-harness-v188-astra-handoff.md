# DeepSeek Harness continuation

This handoff keeps the next owner focused on restoring the real trajectory path. Offline image
work is development infrastructure; strict single-use consumption starts at the provider/task
boundary.

| Field | Current value |
| --- | --- |
| Updated | 2026-09-06 15:34:03 +08:00 |
| Checkout | `/data2/jiadongzhu/Agent/VeriGym` |
| Source before this change | `main` and `origin/main` at `642053bd38574f3baae52e61c09caf12dd6d29bc` |
| Current work | Uncommitted v188 root-headroom simplification plus this handoff |
| Immediate goal | Merge the 4-GiB gate, run v188, then qualify PR-1816 |
| Provider state | No v188 provider client, request, token, task, or trajectory |
| Local HWE images | The complete public GHCR set is present under `/data2/jiadongzhu/Agent/hwe-bench-public-images`; the completed-download layer cache has been removed |

## Do next

1. Review and commit the current focused change, including this handoff. Do not stage or edit the
   seven unrelated user-owned untracked files listed below.
2. Run only the focused v188 tests and style checks shown below. Let the ordinary PR CI provide the
   broad regression pass; do not repeat every historical campaign suite locally without a concrete
   failure suggesting it is needed.
3. Merge the focused PR and use its successful post-merge `main` run ID for v188. This is required
   because the existing launcher checks clean merged source, not because offline image development
   needs a new campaign for every edit.
4. Run v188 once under its existing identity. Inspect its result and cleanup.
5. If v188 succeeds, perform the existing v189 requirement as a narrow receipt and artifact review.
   Avoid a new generic audit framework or another full local test sweep.
6. After that review, move directly to PR-1816 base-FAIL/reference-PASS qualification on the open
   toolchain and official HWE verifier, followed by the single research canary if qualification
   passes.

If the offline build exposes another ordinary prerequisite, preserve the terminal receipt, fix the
root cause in one focused successor, and test it locally before freezing it. Do not create a chain
of separate versions merely to inspect, classify, and reclassify the same zero-provider build
failure. Never relabel or retry a provider-started task.

## Current change and verification

The v188 control-root threshold is now 4 GiB (`4,294,967,296` bytes); the `/data2` threshold remains
50 GiB (`53,687,091,200` bytes). The control process writes only bounded state to `/`. DinD backing,
scratch, experiment output, and the exported image are all on `/data2`, so the root gate should not
reserve bulk image space a second time. Four GiB also matches the control-root floor used by the
ordinary DeepSeek Harness campaigns.

Changed paths:

```text
SECURITY.md
configs/training/qwen35_hwe_deepseek_harness_v188_git_builder_repair_v1.json
docs/hwe_deepseek_harness_collection.md
integrations/verigym-deepseek-harness/tests/test_v188_git_builder_repair.py
src/verigym/hwe/open_toolchain_git_builder_repair.py
tests/unit/test_hwe_open_toolchain_git_builder_repair.py
todo/2026-09-06_deepseek-harness-v188-astra-handoff.md
```

Run the focused checks:

```bash
cd /data2/jiadongzhu/Agent/VeriGym
pytest -q tests/unit/test_hwe_open_toolchain_git_builder_repair.py
pytest -q integrations/verigym-deepseek-harness/tests/test_v188_git_builder_repair.py
ruff check src/verigym/hwe/open_toolchain_git_builder_repair.py \
  tests/unit/test_hwe_open_toolchain_git_builder_repair.py \
  integrations/verigym-deepseek-harness/tests/test_v188_git_builder_repair.py
ruff format --check src/verigym/hwe/open_toolchain_git_builder_repair.py \
  tests/unit/test_hwe_open_toolchain_git_builder_repair.py \
  integrations/verigym-deepseek-harness/tests/test_v188_git_builder_repair.py
```

The updated manifest identities are:

- file SHA-256: `e5b2c868b7c9bce62e68969b5f8d05fe5ed3829f84900cdbd31ac1c043044e0b`;
- canonical manifest hash: `4b4006624942229ea408c60c16565febb8b81537278ed429fceafe6b2cd66c69`.

## Run v188 after merge

Use a short preflight: confirm merged source, local inputs, capacity, and fresh output paths. There
is no need to re-audit all predecessor history before this offline build.

```bash
cd /data2/jiadongzhu/Agent/VeriGym
git status --short --branch
git rev-parse HEAD origin/main
sha256sum \
  configs/training/qwen35_hwe_deepseek_harness_v188_git_builder_repair_v1.json \
  /data2/jiadongzhu/Agent/datasets/tools/open-builder/v188/git-package-closure.tar \
  /data2/jiadongzhu/Agent/datasets/tools/open-builder/v188/git-package-closure.tar.sha256

root_free=$(df --output=avail -B1 / | tail -1 | tr -d ' ')
data2_free=$(df --output=avail -B1 /data2 | tail -1 | tr -d ' ')
test "$root_free" -ge 4294967296
test "$data2_free" -ge 53687091200

test ! -e /data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v188-git-builder-repair-v1
test ! -e /data2/jiadongzhu/Agent/.verigym-tmp/deepseek-harness-v188-git-builder-repair
test ! -e /data2/jiadongzhu/docker/deepseek-harness-hwe-v188
```

Resolve the successful run for the newly merged threshold change and pass its numeric ID:

```bash
post_merge_run_id=$(
  gh run list --branch main --commit "$(git rev-parse HEAD)" --status success \
    --limit 1 --json databaseId --jq '.[0].databaseId'
)
test -n "$post_merge_run_id"
VERIGYM_RUN_DEEPSEEK_HARNESS_V188_GIT_BUILDER_REPAIR=1 \
  python scripts/launch_hwe_deepseek_harness_v188_git_builder_repair.py \
  --post-merge-main-run-id "$post_merge_run_id"
```

The current v188 identity still accepts only the seven frozen untracked paths below. Committing this
handoff with the threshold change avoids the previous temporary move-and-restore workaround:

```text
configs/training/qwen35_hwe_openhands_v56_direct_oci_provisioning_v1.json
integrations/verigym-openhands/src/verigym_openhands/hwe_v56_direct_oci_provisioning.py
scripts/download_hwe_bench_public_images.txt
src/verigym/hwe/oci_resumable.py
src/verigym/hwe/public_ghcr.py
tests/unit/test_hwe_oci_resumable.py
tests/unit/test_hwe_public_ghcr.py
```

Inspect only the outputs needed to decide whether the repair worked:

```bash
result_root=/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v188-git-builder-repair-v1
python -m json.tool "$result_root/zero-provider-report.json"
python -m json.tool "$result_root/cleanup.json"
docker ps -a --filter label=verigym.owner=deepseek-harness-hwe-v188-git-builder-repair
docker volume ls --filter label=verigym.owner=deepseek-harness-hwe-v188-git-builder-repair
```

Success means the repair succeeded, the final image archive and sidecar were exported, cleanup is
complete, and HWE/provider counters remain zero. Do not invoke the same v188 identity a second time
after it creates a terminal result; the existing implementation requires a fresh output identity.

## Continue to the experiment

The next meaningful experiment is PR-1816 dual-route qualification:

The complete collection of official HWE-Bench prebuilt images publicly released on GHCR is already
downloaded under `/data2/jiadongzhu/Agent/hwe-bench-public-images`. The current local inventory has
177 Docker tar archives, 177 matching SHA-256 sidecars, and no `.partial`, `.part`, or `.tmp` files.
Use this local collection for later tasks; do not pull the same HWE images from the registry again.
The completed-download `crane-layer-cache` was removed after confirming that no campaign runtime
references it. This reclaimed `61,268,738,048` bytes (about 57.1 GiB) and reduced the collection to
about 310 GiB without changing any archive, sidecar, or digest lock. PR-1816 passed both its
SHA-256 check and `crane validate` after the deletion. A future registry download will no longer
benefit from the old shared-layer cache. The pre-existing downloader process from the other
checkout remains suspended and was neither stopped nor resumed; it held no cache file open.
PR-1816 is available at the following exact lock:

- HWE archive:
  `/data2/jiadongzhu/Agent/hwe-bench-public-images/docker-tar-archives/lowrisc_m_ibex/pr-1816.tar`;
- archive SHA-256:
  `91395d522a65b0ae35f9c4504d74aa5a460242ab6629bcdfb1155c6cbc6821ed`;
- official verifier image:
  `sha256:7ad60e4cd099379b038d99def95f3a310d2f636116d8790f778b1f93ee2f20f7`.

Qualification must show base-FAIL/reference-PASS with both the repaired open-tool route and the
official verifier. If it passes, run one DeepSeek v4 Flash research canary with seed/sample
`503/19`: the agent sees only open tools and the final candidate is judged by the official HWE
verifier. Keep that trajectory research-only; do not automatically mix it into official-route SFT
data.

Apply the stricter controls at this point: freeze task/source/image/toolchain identities, keep
verification at `network=none`, protect credentials, and treat a provider-started task as consumed.
Formal collection, SFT, training, and production readiness remain disabled.

VCS remains safety-prework only. Do not run untrusted HWE RTL through host `LocalRuntime`; a real
HWE+VCS experiment requires a separately controlled licensed verifier endpoint.

## Compact evidence chain

| Evidence | Finding | Continuation path |
| --- | --- | --- |
| PR 215 and main run `34004192438` | The v188 implementation previously passed CI but has not run. | Merge and validate the 4-GiB adjustment before execution. |
| Local git package archive SHA-256 `315102c5bf97a839d7f4fcedfed79fd788ac20796e4f7008e84928c2b7541773` | The offline repair input is complete; no download is needed. | Run the repaired builder with `network=none`. |
| Bulk v188 paths resolve under `/data2` | Root stores bounded controller state rather than image data. | Gate `/` at 4 GiB and retain the 50-GiB `/data2` gate. |
| Local HWE inventory contains 177 tar archives, 177 checksum sidecars, and zero partial files; PR-1816 revalidated after cache removal | The complete public GHCR image collection remains usable without `crane-layer-cache`. | Reuse local archives; expect a fresh download to lack layer-cache acceleration. |

Repository references:

- [`docs/hwe_deepseek_harness_collection.md`](../docs/hwe_deepseek_harness_collection.md)
- [`docs/audits/2026-09-06_deepseek-harness-v187-v186-result.md`](../docs/audits/2026-09-06_deepseek-harness-v187-v186-result.md)
- [`SECURITY.md`](../SECURITY.md)
