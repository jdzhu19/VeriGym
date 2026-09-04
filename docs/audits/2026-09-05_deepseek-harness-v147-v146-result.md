# DeepSeek Harness v147 audit of the v146 environment-boundary scaffold

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v146-environment-boundary-scaffold-v1` is consumed and stopped fail-closed.
It fixed the v144 launcher boundary, completed all five offline HWE task materializations, proved
base-FAIL/reference-PASS for all five tasks, built and v2-scanned all five task-specific command
images, passed all five explicit 300-second command-image identity probes, and passed the
synthetic network-isolated Harness initialization. It then failed at the final socket cleanup
policy check before an atomic scaffold contract could be published.

The terminal status is `stopped_without_execution_scaffold`, the stop reason is
`ConfigurationError`, and the report canonical hash is
`33618a7ee2790a1f2b5d9c93c2701f8f7c33dce69cfa812bfee8935dff552565`.
No provider request, model process, candidate task execution, modification, trajectory,
collection, or training started. All five tasks remain provider-unconsumed. The planned
`deepseek-harness-hwe-v148-official-matrix-v1` identity is unreachable and is not authorized.

## Implementation and merge gates

- v146 implementation commit: `a59964ccaae08804609d23c6281cf51d70182e56`
- v146 authorization merge/source commit: `6347bec37031d8855993e5e117b521476d92851a`
- v146 pull request: [#172](https://github.com/jdzhu19/VeriGym/pull/172)
- v146 branch-push run: `33912903344`, eight of eight jobs passed
- v146 pull-request run: `33912908564`, eight of eight jobs passed
- v146 post-merge `main` run: `33913325892`, eight of eight jobs passed
- v146 manifest file SHA-256:
  `10876458660405dfe46e5402fd23ac2f1f837a05e868dda1c0c7d0e4b51ef3fd`
- v146 manifest canonical hash:
  `4c641ae0c6fb09c4918c0ef154081962da245f6460940df1a6d73abbcfde0335`
- v146 launcher SHA-256:
  `4dc728a6efce37236e7de472d497c6a6d73520a2ea445792c75e9824ae630b23`
- v146 runner SHA-256:
  `a1da105f851abc99ac313691f5923f4174de996171f7a445a88fa23e7c53a4a5`
- v146 authorization SHA-256:
  `37e006469de32ef77f8d5b72383d82490066af86f4a9e0aa83779724b9e222ec`

The source was the exact merged `main` commit after the post-merge gate. The frozen launcher
removed the same 12 provider-configuration names enforced by the runner plus `DOCKER_HOST` and
`DOCKER_CONTEXT`, then established the fixed child-boundary marker. It selected blocked names
before value access and emitted no provider value.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v146-environment-boundary-scaffold-v1`

It contains 1,785 directories including the root, 10,490 regular files, zero symlinks, and no
other filesystem objects. The regular-file modes are 63 files at `0600` and 10,427 prepared
public-source files at `0644`. All 48 recognized VeriGym canonical self-hashes validate. The
terminal report and progress files are byte-identical. An in-memory scan compared the three
available distinct nonempty provider values with every evidence file without printing or hashing
those values and found zero matches.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `8d19c4d28869b4c08133cb40348d75856785c6e6250ecd2714118ec74d9bb815` | `33618a7ee2790a1f2b5d9c93c2701f8f7c33dce69cfa812bfee8935dff552565` |
| headroom preflight | `e0d97fd2ec92d772f44ab41c50f0a50509e262367d1feec816be3a646896b085` | `c4fb2dd03cf40ec8b8ad52c840f8ad481e7bfab85aa1aa4c97a5da394d9c70ad` |
| DinD runtime | `654ccc169207eefa53da17680e34a0a1de5621793bf4d98870e0ab250f031c0c` | `b36b4dd1bca70e268bfa11f5b959f8eccb2b442068d91abe08c392bea049ed83` |
| image-transfer set | `43f080bb57f0f2e7dd8055f9811e46bce04e57cea9b4d786b68667ad3e805a89` | `453ff290416065d29ad36b82019e0f4bd226a7a56ec1dc6f01c10116fda8ce56` |
| task-materialization set | `d973e6fa633252b62ae076829e129228afc8437764e9917fbc288d12d26772fa` | `d9869963c37659b923f2c13acdc074142e9e0e3d2530c7ca1f48e86fa3756f66` |
| execution/final inventory | `8b5da175b1d68fa91b11d1005099868d51f0bd3086b6bef70f9dabbc5cf6aaf2` | `a8cacad58df9f4ec41691abac56bf29090cebad91b0a63e933c870ac03010313` |
| runtime preparation | `ff78ac9a5b4092d13e12f149ff431ec609554457e5b07577b5bc7641b931bbb3` | `c9b94a1d97d5f5e0f829c1febf224db9dd0f3d31da1618a2ddcc3f199ee0e614` |
| command-probe diagnostic | `b1cab8361dbfc799e0728c03ea2c564a984f18738e03f5d0b9e6245a85be3ae4` | `424f1ae6253b4723b305aabe04cc716e0d48f7848f751593db658b6059c61cf3` |
| Harness initialization | `07d10957ba96d975a7b3910cf87d00e993fd4e3b5acde79d8dce4d2c7e2a6b79` | `1c588b139acfb852d12cb3238c2027880227181202bbd9458dcdda06bd319636` |

The report records `provider_execution_authorized=false`,
`provider_execution_scaffold_published=false`, `provider_request_started=false`,
`provider_calls=0`, `model_process_count=0`, and no raw exception. No cleanup receipt or provider
contract exists.

## Five-task and runtime result

All five completed local archives passed their frozen SHA/digest/OCI/config/repository checks and
were explicitly imported through the v146 nested Unix socket without registry access or
`.partial` input. Every official verifier ran with `network=none`, used the unchanged task and
900-second test bound with the separate 300-second Docker control bound, and produced the
expected base failure and reference pass without an infrastructure error.

| Task | Base | Reference | Verifier-control diagnostic hash |
| --- | --- | --- | --- |
| Ibex PR-465 | FAIL | PASS | `afab6bfe53ddc8c7cb58675ce22be796dd7ef7464fcb7d01ba692ff587fda032` |
| Ibex PR-1135 | FAIL | PASS | `2751b0a21dbd287b2a057e21c4691b2bd9f75dc9673fa804d83935a50acbd16c` |
| Ibex PR-1780 | FAIL | PASS | `056d7b54c33c577235b80eb867892d58404f732c4da4fb8cbec9bf4e4ad0b1f5` |
| CVA6 PR-2017 | FAIL | PASS | `1f8e717d10f1ccd21f4e58ebbf32b8a2a4d4354e0325eec583c8369b1faee594` |
| CVA6 PR-2711 | FAIL | PASS | `1edc76f57b6f111f3bb879e286d79b105a7b1db12a06f3086cf494ba8fe6d539` |

All five credential-free, Codex-free task command images passed the bounded v2 security scan and
produced fresh locks. Both pre- and post-probe inner inventories contained every required image
and no container or volume. The content-free probe diagnostic is `passed` with category
`all_command_image_probes_passed` and all five ordered task IDs. The subsequent synthetic Harness
initialization is also `passed` with `provider_request_started=false`. This proves that the v142
command-image identity-probe blocker and the v144 launcher blocker are both fixed.

## Cleanup failure classification and resource disposition

After the final empty inventory, the outer v146 DinD container was removed. The runner then called
the inherited v142 socket-cleanup implementation. That implementation compares the manifest
against the literal volume name `verigym-deepseek-harness-v142-dind-socket`; the correct v146
manifest supplies `verigym-deepseek-harness-v146-dind-socket`. It therefore raised the fixed
`v142 socket cleanup policy changed` configuration error before creating a cleanup helper or
receipt. This is a deterministic identity-binding defect, not a task, image, verifier, probe,
Harness, capacity, or provider failure.

No v146-labelled container remains. Exactly two correctly labelled local bind volumes remain:
`verigym-deepseek-harness-v146-dind-data` with role `data` and
`verigym-deepseek-harness-v146-dind-socket` with role `socket`. Their bind devices are the exact
v146 paths under `/data2`. The data backing was not opened or inspected. The socket backing is
root-owned mode `0755` and still contains the stopped daemon's socket/runtime entries because the
cleanup helper was never allowed to start.

Both volumes and the evidence tree are frozen. They must not be reopened, mounted, mutated,
relabelled, retried, deleted, or promoted by an official provider campaign. A future cleanup
successor may remove only the exact owner-checked v146 socket artifacts under a separately
authorized content-free cleanup policy; it may not inspect the retained data volume.

## Successor boundary

V146 must never be rerun. V147 is only an independent result audit and authorizes no execution. A
fresh provider-free successor may use the next unused identity and fresh bind-backed `/data2`
resources to repeat the complete scaffold. It may change only the socket-cleanup identity binding:
the cleanup predicate must use the successor's exact manifest volume, owner, and backing path
rather than a predecessor literal. The five-task schedule, local archives, official verifier
semantics, command-image scans, 300-second identity probes, environment launcher, and synthetic
Harness behavior remain unchanged.

Any cleanup ambiguity or other failure must again stop fail-closed. The official DeepSeek matrix
moves to a later unused identity and remains unreachable until a complete provider-free successor
is independently audited, merged, and followed by eight green post-merge `main` check classes.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
