# DeepSeek Harness v161 audit of the v160 contract repair

Date: 2026-09-05

## Decision

The single authorized execution of `deepseek-harness-hwe-v160-contract-repair-v1` completed and is
consumed. It must not be rerun. The complete inherited five-task v158 scaffold contract was
reconstructed from immutable evidence and atomically published under the v160 identity. The
terminal status is `completed_pending_independent_v161_audit`; the report canonical hash is
`ecf75224cf902f8bfcef51d2fd7d29abbca942a4f09b842a71dd9cb543b5da7c`.

This was a zero-provider metadata repair. No provider request, model process, task execution,
candidate modification, trajectory, image import, registry access, collection, or training
started. The v158 data volume was not mounted, inspected, mutated, removed, or reopened. The
published contract remains non-authorizing. After this audit is merged and its post-merge `main`
workflow passes all eight required job classes, a separately reviewed v162 implementation may
authorize exactly one official five-task matrix against the retained volume's one-reopen budget.

## Implementation and execution gates

- v160 implementation commit: `cd857c606763c24447300b058e0b656f300e3503`
- v160 authorization merge/source commit: `2c297e73adabc497beb1d09d43e7000ef24d94d2`
- v160 pull request: [#186](https://github.com/jdzhu19/VeriGym/pull/186)
- v160 branch-push run: `33964663732`, eight of eight jobs passed
- v160 pull-request run: `33964683714`, eight of eight jobs passed
- v160 post-merge `main` run: `33964907719`, eight of eight jobs passed
- v160 manifest file SHA-256:
  `4bd0a1402c2ebd7e5f734412e4081e1bbafbb2ff59ba1228aa5ca21b111d1498`
- v160 manifest canonical hash:
  `b89dee2c3b6068cd228cc0a395eb354f7c189dd855df02e8edf5a29b026ecd9f`
- v160 runner SHA-256:
  `d8e770a1be2da8e7138f402701bb4e6a3593f3c4737e64a799cfb6f404e5c393`
- v160 launcher SHA-256:
  `913b90cf940785d2665945f6e124043591e0814c6469a75c4c71e198c074bfe2`
- v160 authorization SHA-256:
  `19596b4f8fba132e5283dd06f3747261c65e90a35eb26e05beba256fde628e64`
- campaign implementation SHA-256:
  `e0e58c87a0463a292a55fa6fbb12c72f2753e2d75bf90fb08ecb3635bd7686ca`

The launcher was invoked exactly once from clean merged `main` with post-merge run ID
`33964907719`. It selected environment names before values, removed all twelve provider
configuration names plus `DOCKER_HOST` and `DOCKER_CONTEXT`, and then started the provider-free
child.

## Immutable execution evidence

The frozen v160 evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v160-contract-repair-v1`

It contains one directory including the root, seven regular files, zero symlinks, and no other
filesystem objects. The root is mode `0700`, owned by UID 1004/GID 100; every evidence file is
mode `0600`. All seven canonical top-level self-hashes validate, and the terminal progress and
report are byte-identical. The evidence-tree hash is
`7491baf8c0c3018893433a5ea014b60e2458e45da0021a372bbcad0a7f23a4f5`.

An in-memory audit scan compared the three available distinct nonempty provider values with all
seven files and 45,673 bytes, without printing, persisting, or hashing those values. It found zero
matches.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| predecessor validation | `dbcfc00274cb8532b2ebb2a2944bf8557ccb56aba22916d9b9635defc0825ba2` | `a39ac21017ec82e988e503c65483c19655959243c2249475997faa87619adb14` |
| volume metadata | `bfa531659e6e8274ee106e1790676602a6420c5d1cda2063954eee988e1cfc54` | `403782fc739df1200c8e7edbc9e4493b8d9b980e53d7e502678d2c03e05f2522` |
| repaired Harness initialization | `0426e52a67dc7e9433bbd2e806ef21b74359af37a7b7624bd8c2f66de08b2608` | `46894d11641981cb40a206de6249c29bdf270d82ff91d0365bd4e2105f895ae4` |
| contract repair | `43192d0dfcd588fe11b554fba1ada5d93361113c0ecd62f5014786474ecfb641` | `cf44cf8a10756f9801d5a3726172bce60423f66be47406e5b6b4a20d6ff8be63` |
| execution-scaffold contract | `946140365117c08d93bf3042761b3743e7fbd5f5fd29293bcc1bcb4852a2a549` | `09f5e86efb97fc18d8abf1b0aa9973841280a0eb2b89aec4624b0b01d955d5bc` |
| report/progress | `6feba2fba7a6e4b9d87e89dc6ed1854f403462d695eff50cd73f71ce810b7f00` | `ecf75224cf902f8bfcef51d2fd7d29abbca942a4f09b842a71dd9cb543b5da7c` |

## Repair result

The predecessor validator rechecked the complete frozen v158 tree: 1,786 directories, 10,492
files, zero symlinks, 45 recognized canonical self-hashes, 20 semantic JSON records without a
top-level self-hash, and tree hash
`b1c844b0827ed68621aba75ad0aa8db81cfc9ff5aab84dc28f8361cef935e130`.
It also revalidated all frozen implementation, authorization, audit, report, task-set, inventory,
runtime-preflight, Harness-preflight, command-probe, runtime, transfer, and cleanup bindings.

The original canonical Harness receipt had an empty synthetic-value scan, split
`values_persisted=false` and `values_hashed=false`, no provider request, and zero provider calls.
V160 added only `provider_values_persisted_or_hashed=false` to an in-memory copy. It recreated the
three persisted task-image mappings in the frozen PR-465, PR-1135, PR-1780, PR-2017, PR-2711 order
and invoked the unchanged v158 pure contract-builder chain. The resulting reconstructed v158
contract hash is `806f05d813fa9a7d5fb70cfb1577a703df1dcca8ea43adb4857cf32516de07bd`.

The final v160 contract binds the current source commit and green post-merge run, all five
base-FAIL/reference-PASS qualifications, all five v2-scanned command images, the exact official
verifier identities, the explicit nested endpoint preflights, and the separate v158 cleanup
receipt hash `2ed3de870e6f03608b975649aa8149a911dbbc8b5a7f5318f21feea1ec689083`.
It records `provider_execution_scaffold_published=true`,
`provider_execution_authorized=false`, provider successor
`deepseek-harness-hwe-v162-official-matrix-v1`, reopen budget one, reopen count zero, and zero
provider calls.

## Volume and successor boundary

The retained volume remains `verigym-deepseek-harness-v158-dind-data`, with the exact v158 owner
and `data` role labels and bind backing
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v158/data`. The backing remains a non-symlink
directory at mode `0710`, UID/GID `0:0`. No container uses the volume and no v158 socket volume
exists. V160 queried only this metadata; its receipt confirms content mounted, content inspected,
and mutation are all false.

V160 and its output are now frozen. V162 must bind the exact v160 manifest, implementation,
authorization, report, contract, evidence tree, this v161 audit, and the later green post-merge
`main` gate. It must preserve seed/sample `502/18`, the five-task order, the DeepSeek v4 Flash
protocol and limits, exact Qwen tokenizer admission, failure/consumption rules, official verifier
identity, and `network=none` task/verifier controls. It may reopen the retained data volume at most
once and must stop fail closed on any drift. No provider execution is authorized by this audit
alone.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
