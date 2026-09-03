# DeepSeek Harness v95 audit of the v94 runtime-complete scaffold

Date: 2026-09-03

## Decision

The one authorized `deepseek-harness-hwe-v94-runtime-complete-scaffold-v1` execution is
validly closed as a pre-provider configuration stop. It published no execution scaffold,
started no model process or provider request, and consumed no provider call. The v94 identity
and retained data volume are frozen and must not be retried or reopened.

The failure does not indicate task, verifier, or security drift. PR-465 reproduced the required
base-FAIL/reference-PASS qualification with the frozen source and official verifier identities,
then passed the complete v2 command-image security scan. It stopped because the newly rebuilt
command image did not reproduce v90's historical derived image ID. That historical-ID equality
was an invalid cross-build requirement.

Because v94 did not publish the prerequisite contract, its reserved v96 official-matrix identity
is retired unused. A repair must use a new scaffold identity, a fresh `/data2` DinD data volume,
and a later separately authorized provider identity.

## Authorization and execution identity

- v94 authorization merge: `350bc0fa0151c37cc27f939d68c5a927fdc64d0f`
- v94 post-merge `main` run: `33770774222`, all eight required check classes passed after a
  failed-job-only rerun of one timing-sensitive fake-Codex test
- manifest SHA-256:
  `45a3e0132f6a31e70cb17ebd665e556c84ffa4300de429c8f4c4e9d54dbca27c`
- source commit recorded by the result:
  `350bc0fa0151c37cc27f939d68c5a927fdc64d0f`
- audited predecessor: v93 merge
  `04ce5601446078db6084c90ac0eb812807807d0b`, post-merge run `33766642633`
- predecessor v92 report hash:
  `f392a5bc3534d6c6daaf953a63d9520ab95ef73ec4d7a904ce8fed1ab35b1c42`

The first `main` attempt's Docker failure was not used as campaign evidence. The unchanged tree
had already passed both PR runs, and only the failed job was rerun before v94 execution.

## Result integrity

The result root is
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v94-runtime-complete-scaffold-v1`.
It contains 282 regular files totaling 2,524,500 bytes and no symbolic link. The report and
progress file are byte-identical:

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| `execution-scaffold-report.json` | `2fac9b56f15a0216fbdfee85018b8885a0f9377d8521cb75bbb0b101a7609c57` | `29202688ef99ebed3381b7dcb448cab6bb6db923f5034352e677b7e63515ad12` |
| `execution-scaffold-progress.json` | `2fac9b56f15a0216fbdfee85018b8885a0f9377d8521cb75bbb0b101a7609c57` | `29202688ef99ebed3381b7dcb448cab6bb6db923f5034352e677b7e63515ad12` |
| `dind-cleanup-receipt.json` | `dcc9c0cb149f381cb8250088c10246133c579fef9a7ccb87c3f9a9ed6620d6ca` | `c0df6a1a9f202c0b62f96901c363a31af874a54c448127bd5ed4bd30beeded05` |
| `headroom-preflight.json` | `1cbe79402155c6d643f9989870274fb02570414bc4cf6afb4c0d7e1fb7410fef` | `862193745fb5c74cfe07b88a04c33378bae3e2c6765581fef373adb7d5fa0106` |
| `image-transfer-set.json` | `744460f45da9f18b73c1b0d8605a29383efe2795a1ec2f91055ace6e98c5b71d` | `add304e87bac130b0c72e9128f1c94ed8a8853e0f0d62c0ed3a6994bb2d78274` |

The report records status `stopped_without_execution_scaffold`, reason
`ConfigurationError`, and only the completed stage
`controller_and_workspace_runtime_transferred`. It also records
`provider_execution_scaffold_published=false`, `provider_request_started=false`, zero provider
calls, and zero model processes. No `execution-scaffold-contract.json` exists.

## PR-465 qualification and lock comparison

The first task passed all checks that precede the historical-ID comparison:

- offline archive receipt SHA-256:
  `21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516`
- archive receipt hash:
  `fc1af152a1ba03044119cf9ce230294498303591f65302299502c679be7c9d63`
- qualification smoke-report SHA-256:
  `f31aef682ef74774205da019fefa70327f13af028e00b4a88038432c49b70f0e`
- qualification: `base_failed=true`, `base_infrastructure_error=false`, and
  `reference_passed=true`
- source-image-lock evidence SHA-256:
  `9f2b2f43e3577f418f0e5bcf24cdaac0960e40d324a0330611c92fbfda66d87a`
- source lock hash:
  `f32616351ff822c6417fc566d34077f30570f73acc8b25d877cf8c6c765f2de7`
- command-image build receipt SHA-256:
  `44900effc8eb48ffd1b0a32d0b6e7e8f80dda2e19dacf4dce0cfa0c9af606b8c`
- security-scan evidence SHA-256:
  `d82b5e77c14342da8c12af8da0d5bbc7553c29006b44fcb77f1c4e376717781d`
- scan result: `scan_passed=true`, `secrets_detected=false`, with all 29 v2 checks true

The immutable source and verifier bindings did not change:

| Binding | v90/v92 expected | v94 observed |
| --- | --- | --- |
| prepared source image lock SHA-256 | `cd89cd593ea6989ca50e20260720d63e468f68e98572636e1890d8b90d2a21b3` | same |
| official verifier image | `sha256:d0d2c8a6391c3c35a2fc2e6e310786d65d0f0c4c9f08f6fcec5098d0be34c410` | same |
| derived command image | `sha256:1ad1a577a7b9abf6b0ee2c2f7ff8f9418887fe53ff81f321513fabb1f0be569e` | `sha256:1f07244942ae2ef52a299938080f1427847c3f5f08fbe7dcf5899f8e743941bb` |
| command-image lock hash | `bc2736ba1d50af094a12ab665fef39b1bf90dc55168a41d6882c8f08b30868a1` | `56d29fb4ad71d7c19f9b44cbd82d1738a9fd128b6776f681fe2ff3b99892b580` |
| security-scan ID | `44125da23889c12c493f666f6c359cfc4f87c60300dc6d0f3fa26c527c8c995b` | `b4f1435168d7050ec59adba5c7900c2dd055b518e6b1e3f06706fbc7d0d57eb5` |

The unsanitized image also changed from
`sha256:2659a2209f43ac395154be05b7ec4e2aa1621c15ddc91af0ff5f371f0ab84102`
to
`sha256:075da5804689f23eaf6c3521d2edad91f358f99b7ef71ca07c27df2f7505d758`.
The repository sanitizer intentionally preserves filesystem layers and rewrites only image
configuration environment/user fields. It does not normalize the input image's `created` or
history timestamps. Consequently, a new Docker build is not specified to reproduce v90's
unsanitized or derived config digest even when its source, tools, filesystem behavior, and
security properties are equivalent. The derived lock and scan IDs necessarily follow the new
image identity. V94 correctly failed closed, but its equality requirement was too strong.

## Cleanup, storage, and credential boundary

- No v94 campaign container remains.
- The socket volume is absent. The retained data volume is a local-driver bind volume with exact
  device `/data2/jiadongzhu/docker/deepseek-harness-hwe-v94/data`.
- Cleanup completed and is confirmed by the sealed receipt. The outer DinD daemon remained on
  network `none`; no registry or partial archive was used.
- An independent in-memory scan compared all live nonempty provider values against 282 regular
  evidence files: zero matches. Values were not printed, persisted, or hashed.
- No partial successor contract exists. The v94 volume is retained only as frozen audit evidence.

## Successor boundary

V95 authorizes no provider access and no execution by itself. After this audit is merged and its
post-merge `main` commit passes all eight Actions classes, a v97 zero-provider repair may be
implemented and separately authorized. It must use fresh paths rooted at
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v97`, must not reopen any previous campaign volume,
and must validate all five tasks from completed local archives.

The v97 contract may freeze newly materialized command-image identities only after each image has
passed its task-specific base-FAIL/reference-PASS qualification, source/verifier/tool locks, and v2
security scan. It must compare source, official-verifier, tool, behavior, and security semantics to
the audited predecessor; it must not require a fresh Docker rebuild to equal a historical derived
image ID. Provider execution remains a separate later identity after an independent result audit.

## Closed policy

Both migration conclusions remain false. There are no candidate SFT tasks, research trajectories,
or authorized imports. Failed context is audit-only. The following remain false:
`formal_collection_allowed`, `formal_collection_started`, `collection_started`,
`training_started`, and `production_training_ready`.
