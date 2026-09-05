# DeepSeek Harness v157 audit of the v156 command-runtime diagnostic

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v156-command-runtime-diagnostic-v1` completed successfully and is consumed.
It confirms that the v154 PR-465 pre-provider failure was caused by constructing `DockerRuntime`
without an explicitly bound nested-Docker transport. The unbound probe produced the allowlisted
subreason `image_missing`; the otherwise identical runtime configuration passed when constructed
with `DockerCliEngine(docker_host=<fresh nested socket>)`.

This is a zero-provider infrastructure diagnosis, not a model, task, official-verifier,
trajectory-collection, or benchmark result. V156 executed no task command, base/reference
verification, Harness controller, provider request, candidate generation, collection, or
training. Formal collection, SFT, and production training remain disabled.

## Implementation and merge gates

- v156 implementation commit: `b8a7730c163e37725ebd132a7292fb502d0754b7`
- v156 authorization merge/source commit: `36955fab4c89178ae75eb05764d56727d2df0207`
- v156 pull request: [#182](https://github.com/jdzhu19/VeriGym/pull/182)
- v156 branch-push run: `33958769920`, eight of eight jobs passed
- v156 pull-request run: `33958778332`, eight of eight jobs passed
- v156 post-merge `main` run: `33958990919`, eight of eight jobs passed
- v156 manifest file SHA-256:
  `8cd2051aa91cbc9d36b84c505964c9e88000a61ff8a6b2e06101b3f28a4b42bc`
- v156 manifest canonical hash:
  `c2ced9bc5a19e725b58ff3acc26db956459162c32b025c557c1c4644114c320e`
- v156 runner SHA-256:
  `09606537c2ad63f7112ef9fad015e548305652301fee33328be3b06cea3d5faa`
- v156 launcher SHA-256:
  `9c9d16626142900f2264b12cce4809ce11ee2be67c51a9779f2c2bd1695942cb`
- v156 authorization SHA-256:
  `a474e45f35fa5e42b71376addab7e0647c8da87f514691c4a5dc257b07c1105a`

The launcher was invoked exactly once from the clean merged `main` commit with post-merge run ID
`33958990919`. It removed all twelve provider configuration names and both ambient Docker endpoint
names before starting the child. The child recorded zero provider calls.

## Immutable execution evidence

The frozen evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v156-command-runtime-diagnostic-v1`

It contains seven directories including the root, seventeen regular JSON files, zero symlinks,
and no other filesystem objects. Every directory is mode `0700`; every file is mode `0600`; all
are owned by UID 1004/GID 100. All schema-defined top-level canonical self-hashes validate. The
terminal progress and report are byte-identical. An in-memory scan compared the three available
distinct nonempty provider values with all seventeen files without printing, persisting, or
hashing those values and found zero matches.

| Evidence | File SHA-256 | Canonical hash or ID |
| --- | --- | --- |
| report/progress | `2582bcdf424763bbbccbd8ab1953ac51de0d35fa16e6751002c66bfea4cbc9ef` | `8f5a984f24b15c34eb3e8978ec91aa2c26af8a575058233e2c867777fe700a05` |
| predecessor preflight | `e7777981c00ddaaf5b09477279525059e6fbc2398a0932295612510902a91916` | `a0fdf91e1ccb06edd031cee39e7b4fa529c5a99a7fe7b080092bf6e29ccd8add` |
| PR-465 archive | `21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516` | `fc1af152a1ba03044119cf9ce230294498303591f65302299502c679be7c9d63` |
| explicit archive import | `ed5f5e4d7d68bde78821bcdd876766d69d2bf5650d78fddbf2f94ef581bcdce2` | `ac8aead1abbb47ec87f3a36a7529f6b97be054f517de7dafd6c66a816e28004e` |
| DinD runtime | `e94e267b0ce8d7d9e667c415321a26205f4e897e5ba8f7a8238c2da18a31cd5a` | `12664ebdaad78bd81e144b89e54b9d85704f1134e8dc10332c60dca4f256587e` |
| workspace-runtime transfer | `bf42c875093ff46c2dc81aaafe15929e752a9c1284cd94c7cf301c463923c42a` | `ecdcf3c3626074f4318c469b0a955ea271be41e95e867a7e314c4b451862fd2e` |
| command-image build | `2b072a7be5932e1668452904b2f0c809f79155630bd4c6cba572d5ae4b8f4936` | `01f68a2c15712971fb68f86f2cb9c08ffed4a4e9d36b27f577ad7a913a0a162f` |
| command-image security scan | `78e7d898734fb9ed9566b0925d7668b902c22c6dd7a9e54774424d1197b2086d` | `95cc8c7dd9530a0757cb2659cc28de5d253f3c0aa631ca82b0c28c0fd22699a5` |
| command-image lock | `96e90ee2263f905698172dbaf9c37f8afc2064243cb68da4c14684c72bb38164` | `43e67445ee63b0151d19bee5e88e9b14a8f29a1b2528c41feaba28fdfe70921f` |
| inner inventory | `93d2c0e6edc87ac7087e0e27d23922bed30856bfd955c13a774dbe360792626b` | `3cc06c78c2217cb61b936e89d00e9b8d247e3cf6950852dedb7901a103e1abd0` |
| runtime-binding diagnostic | `59373492d0a539bee20a4bb5ae3967a59fb51f78c11fc865d2dfc3f5f3c3271b` | `73f8a512f5274340843c42cda52c7f094839cdb8cb3481c24940e1f26844fef4` |
| cleanup receipt | `b9f8868b4bb429273b67eb59afee8497a2eec8c92bb8a161ff2b91010b262640` | `4c481462e44aff428e13254a3cf55facbe4c9fc6a9145ef98952dd181d02c37c` |

The terminal report records `diagnosed_pending_independent_v157_audit`, no stop reason, one startup
attempt, successful archive import, successful command-image build and v2 security scan, confirmed
diagnosis, successful explicit-engine probe, confirmed cleanup, and zero provider calls. It binds
source commit `36955fab4c89178ae75eb05764d56727d2df0207` and post-merge run
`33958990919`.

## Diagnosis and scope

The completed local PR-465 archive again passed its SHA-256 sidecar, OCI manifest/config, registry
digest lock, immutable image ID, and `/home/ibex` repository-base checks. It was imported only
through the fresh explicit nested socket. The workspace-runtime image was transferred locally,
and the rebuilt credential-free command image passed its bounded v2 scan. Its lock is semantically
identical to the successful v148 lock after excluding only the necessarily fresh derived image ID,
security-scan ID, and lock hash.

The two probes used the same runtime configuration. The unbound runtime selected the host Docker
daemon because `DockerCliEngine._subprocess_environment()` intentionally does not inherit ambient
`DOCKER_HOST`; it returned `image_missing`. The runtime injected with a `DockerCliEngine` bound to
the fresh nested Unix socket prepared successfully, then closed with zero inner containers and
zero inner volumes. This proves the endpoint-binding defect. The generic `image_missing`
subreason alone does not identify which configured role image was resolved first, so this audit
does not make that narrower claim.

No registry was accessed, and no VPN, proxy, downloader, Docker daemon configuration, shared
Docker network, task source, or HWE verifier was modified. No raw exception, raw Docker output,
credential, provider response, task output, or model output was persisted. Runtime-probe and
command-build output was not hashed; the pre-existing workspace-image transfer policy retained
only bounded hashes and byte counts for its 89-byte stdout and empty stderr, without retaining the
raw stream. No `.partial` archive was used, and the retained v148 data volume was neither inspected
nor mutated.

## Cleanup and successor boundary

Cleanup removed the exact v156 DinD and cleanup containers and both v156 bind-backed Docker
volumes. No v156 container or volume remains. The data backing, socket backing, and runtime scratch
are empty, mode `0700`, and owned by UID 1004/GID 100. The v148 data-volume reopen remains consumed
and must not be granted another reopen.

V156 must never be rerun or relabelled. This v157 audit authorizes no provider execution. After
this audit is merged and its post-merge `main` workflow passes all eight required job classes, a
new official-matrix identity may preserve the unconsumed task order and seed/sample `502/18` only
if every `DockerRuntime` that targets the nested daemon is constructed with an explicitly injected
`DockerCliEngine(docker_host=<locked nested socket>)`. The successor must use fresh `/data2`
resources, revalidate all completed local archives and image/tool locks, retain the existing
fail-closed provider-consumption policy, and receive its own merged authorization and green
post-merge `main` gate before execution.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
