# DeepSeek Harness v139 audit of the v138 fresh explicit scaffold

Date: 2026-09-04

## Decision

The single authorized execution of
`deepseek-harness-hwe-v138-fresh-explicit-scaffold-v1` is consumed and stopped fail-closed. It
validated the frozen predecessors and all five completed local archives, started one fresh
networkless DinD, transferred the trusted controller and workspace-runtime images, and explicitly
imported and identity-checked the Ibex PR-465 HWE task image. PR-465 then reproduced the required
base failure without an infrastructure error, but its reference verifier returned an
infrastructure `timeout` instead of PASS. The terminal status is
`stopped_without_execution_scaffold`, the stop reason is `ConfigurationError`, and the report
canonical hash is `0532764a23d9c50666f4708142135d2c54740b9950239e687905d536a43dde8b`.

The v138 atomic scaffold contract was not published. PR-1135, PR-1780, PR-2017, and PR-2711 were
not materialized. No command image was built or scanned, no command-runtime preparation probe ran,
and no Harness controller, provider request, model process, task modification, trajectory,
collection, or training started. All five scheduled tasks therefore remain provider-unconsumed.

## Implementation and merge gates

- v138 implementation commit: `ccfca2274bc353047873cba503401971a50bf788`
- v138 authorization merge/source commit: `556ff84b0fef7a4d1c728e98825f55d416db92b3`
- v138 pull request: [#164](https://github.com/jdzhu19/VeriGym/pull/164)
- v138 branch-push run: `33863341933`, eight of eight jobs passed
- v138 pull-request run: `33863346542`, eight of eight jobs passed
- v138 post-merge `main` run: `33863712668`, eight of eight jobs passed
- v138 manifest file SHA-256:
  `44d916136f0c52725b43222c208bc9b598531b57a68343b2a90f8956cd24be14`
- v138 manifest canonical hash:
  `82a041fc1a8ee234a08f48178c11699a9b8ef45e50fb110b2d7da234f00a1992`
- v138 runner SHA-256:
  `f77febd523ee7d9653f93a987141e56cf120fe8416a7f05cb56d3e31202cb0d6`
- v138 authorization SHA-256:
  `be15420722a397c3b2b9aa1f49f08cd89ce7804fb96f271054730f81e8c1c525`

The authorized child removed every frozen provider variable and ambient Docker endpoint variable
before its one start. Its source was the exact merged `main` commit after the post-merge gate.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v138-fresh-explicit-scaffold-v1`

It contains 82 directories including the root, 278 regular files, and zero symlinks. Structured
receipts use modes `0700`/`0600`; the prepared public source tree accounts for the expected
`0755`/`0644` entries. Every schema-defined top-level canonical self-hash validates, and the atomic
progress and terminal report are byte-for-byte equal. An independent in-memory scan compared the
four available nonempty provider values with all evidence files without printing or hashing the
values and found zero matches.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `9161ae90c4e4fbf41baa113ef9464e326c7537da51c0cacce47eb14c9a10c24e` | `0532764a23d9c50666f4708142135d2c54740b9950239e687905d536a43dde8b` |
| headroom preflight | `77938efe788f4b9b1d7826cc0de5949907877ec0860aacbde0ab743e3c8454a7` | `23f3d574d87036989ae250cdd0c6b8230989f63215026f82961e978d9aff390d` |
| DinD runtime | `8cef13532a393da7f1ef24c34995a604165b9161f466b2f79ad3f4f77291cafc` | `c50cb7aa5b1fea6660997aaffeb2efb5731254fd8ae749db02b8cb8e7fa57a32` |
| image-transfer set | `200efbb6e5d519e3b637cadb448f4c6c5e0e6117f642f6b99f4cb99920d788f0` | `44d1554c16d8b65d20b0ac9d45490f6028bdf9a58bd4e567dd8460e0d58559ad` |
| PR-465 archive | `21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516` | `fc1af152a1ba03044119cf9ce230294498303591f65302299502c679be7c9d63` |
| PR-465 import diagnostic | `ea53a92fc53a07e04fce0bb8c11274b1ea46f4c0c82bfad1200a460e443df4ce` | `cefeb720b6317762b99397379b1ad91b47cc801a573f47213ab3d1aa0a6c8c53` |
| PR-465 source image lock | `cd89cd593ea6989ca50e20260720d63e468f68e98572636e1890d8b90d2a21b3` | n/a |
| PR-465 base verifier result | `ddb82d2187956283351cac8e8956493ad38254da71fc7b7073f910f9dc55cc70` | n/a |
| PR-465 reference verifier result | `81158120b8573d03e30e7a08246efe2fa9df71b7eeec1580b0ba5f56565d5096` | n/a |
| PR-465 smoke report | `2cfc40ebab3636b9be0333f4330ab20d46d907b49383ca9d6202c2c83cbc6a44` | n/a |
| cleanup receipt | `a42bd7507e2a9d6c731a261f9170e712016ff9136ba4a154aa4c07363ba81d30` | `bca2bfebdcf3a1057769f6407e0903e4aaefdf1fd5a7937b0debfbd94fcda92a` |

## Import result and failure boundary

The explicit PR-465 archive import passed. `docker load` exited zero, the imported immutable image
ID exactly matched `sha256:d0d2c8a6391c3c35a2fc2e6e310786d65d0f0c4c9f08f6fcec5098d0be34c410`,
the absent PR-specific local tag was created, and the final tag resolved to the same ID. Every
operation used the exact v138 nested Unix socket. The diagnostic persisted only exit codes and
stdout/stderr byte counts: it contains no raw Docker output, exception, registry access, provider
activity, or `.partial` input.

The base verifier returned `failed/test_failed`, zero of one tests passed, and
`base_infrastructure_error=false`. Its execution metadata confirms image identity, network mode
`none`, all capabilities dropped, `no-new-privileges`, the built-in seccomp profile, no dependency
volume, and no raw output. The reference verifier returned `error/timeout`, null test counts and
exit code, empty stdout/stderr hashes, and no execution metadata. Thus the immutable result proves
a Docker verifier control-path timeout before a valid reference outcome; it does not support a
reference rejection or a claim that the reference RTL test ran to completion.

The command-image build diagnostic, image receipt, v2 security scan, command-image lock, complete
task receipt, inner inventory, and explicitly bound runtime-preparation receipts do not exist.
Accordingly v138 fixes the v136 ambiguity around HWE archive import but does not reach or validate
the v134 command-runtime fix.

## Cleanup and resource disposition

Cleanup removed the v138 daemon container and socket volume and restored an empty socket backing,
control root, and runtime scratch root to mode `0700` and UID 1004/GID 100. No v138-labelled
container remains. Exactly one owner-labelled volume remains:
`verigym-deepseek-harness-v138-dind-data`, role `data`. Its local-volume metadata lives under the
shared Docker root, but its bind device is
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v138/data`, so the retained image/layer payload uses
`/data2` capacity. The volume and backing are frozen and must not be reopened, inspected, mutated,
or reported as a reusable successful scaffold.

## Successor boundary

V138 must never be rerun. The planned identity
`deepseek-harness-hwe-v140-official-matrix-v1` is unreachable because v138 did not publish its
atomic contract; it is not authorized to execute. A fresh provider-free successor must use a new
identity and new `/data2` data/socket volumes, retain the explicit archive-import diagnostics, and
make verifier image inspection, container creation, execution, and removal separately observable
without raw output. The observed 60-second Docker control bound is too narrow for cold VFS
container creation; a successor may increase only this infrastructure-control bound to a frozen
maximum of 300 seconds while leaving the official verifier test timeout and verifier semantics
unchanged.

Only after all five tasks again produce base-FAIL/reference-PASS, five command images pass their v2
scans, all explicitly bound runtime probes pass, and an independent merged audit is green may a
new official DeepSeek matrix identity be authorized. The v138 failure consumed no task at the
provider boundary, but it cannot be bypassed by treating the base result alone as qualification.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
