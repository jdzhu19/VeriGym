# DeepSeek Harness v149 audit of the v148 cleanup-identity scaffold

Date: 2026-09-05

## Decision

The single authorized execution of
`deepseek-harness-hwe-v148-cleanup-identity-scaffold-v1` completed successfully. It qualified the
five-task official route entirely offline, published an atomic provider scaffold contract, and
fixed the v146 final-cleanup identity defect. The terminal status is
`completed_pending_independent_v149_audit`; the report canonical hash is
`f93038f0e3d9dd9bdf2e1160661b6bb595edc217969f5f41f240c65edce50b1e`.

No provider request, model process, candidate task execution, modification, trajectory,
collection, or training started. Provider calls are zero. Subject to this audit being merged and
that merge's `main` commit passing all eight ordinary Actions classes, the frozen contract permits
one separately authorized reopen of the retained v148 data volume by exactly
`deepseek-harness-hwe-v150-official-matrix-v1`. This audit does not itself make a provider call or
start collection.

## Implementation and merge gates

- v148 implementation commit: `fe458a160541bb0defc4817ee68c517fa8b79c03`
- v148 authorization merge/source commit: `9fd8b1547336190c3dded5feae815dc5b30a849f`
- v148 pull request: [#174](https://github.com/jdzhu19/VeriGym/pull/174)
- v148 branch-push run: `33920700555`, eight of eight jobs passed
- v148 pull-request run: `33920717936`, eight of eight jobs passed after rerunning one unrelated
  flaky Docker test job
- v148 post-merge `main` run: `33921400036`, eight of eight jobs passed
- v148 manifest file SHA-256:
  `6b2a33aa3ecebb4756e6fb2d6b60adef8b0b25e216016326a82f4b9993ba0f67`
- v148 manifest canonical hash:
  `4a44c1547289caea2de14e5743621e83ea72669964458dcaab9e0254dae9cef1`
- v148 launcher SHA-256:
  `caba03bcf127883b4306921ae73d6d1946fe4aa12c1015956bc8dcc6c26ee1ca`
- v148 runner SHA-256:
  `722a3891df425de60d7eb9a581f452540f43c5eebb20a54c42674ff77d806428`

The execution source is the exact merged commit after the post-merge gate. A read-only preflight
proved that all v148 paths, volumes, and containers were initially absent; no `.partial` archive
was present; all five completed HWE archives passed their sidecar, OCI manifest/config, registry
digest, image-config, and repository-base checks; and the exact DinD, controller, and workspace
runtime host image identities were available. No registry was accessed.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v148-cleanup-identity-scaffold-v1`

It contains 1,786 directories including the root, 10,493 regular files, zero symlinks, and no
other filesystem objects. The regular-file modes are 66 files at `0600` and 10,427 prepared
public-source files at `0644`. All 46 recognized VeriGym canonical self-hashes validate. The
terminal report and progress files are byte-identical. An in-memory scan compared the three
available distinct nonempty provider values with every evidence file without printing,
persisting, or hashing those values and found zero matches.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `3c8cbcced4e07fea632c79da7e6d057b5a34a0f96745d0c96c14129c1830c408` | `f93038f0e3d9dd9bdf2e1160661b6bb595edc217969f5f41f240c65edce50b1e` |
| provider scaffold contract | `9cc96c2f6c13d10f7be356945466bc8b9d0c1c7130645882226ec95324ae88ef` | `fc6c7ec4599f8be2f84ec560f381a2f3ddc755def8cd4a6db5a158bcbc4dc278` |
| headroom preflight | `07a4ce5eaa8f0946d13aec024e82e121a46d5ffa2f3d854410cce3a3411e95ee` | `3089b1dcbf83bb44026f8b12753f04da9072e573cb2c1c0a9f796fa523444eeb` |
| DinD runtime | `a68efa2a166a9a805d8896137674543aa861702bcf3e4ea522c94f4a9a03fc68` | `1ca9ecafbe1bbc8a429de52f2e5b9bc9e3f5dc74cbc9a2ec7531ba6565d13c9c` |
| image-transfer set | `6bd1c0cf5e5de5eb4a8f292e11e4ccbe17bf81bb1157214036ca640bea7eaf6e` | `461a6929c27ebfc03ac68a8056880a26be14294f49640c787f2036e7b8b1b625` |
| task-materialization set | `ec9206d1ddd7e1cdc2471accc1a264e2edd5878e69ebcb1eca438b9093efbb03` | `4b5be07b473c205b875643cc5663027b6aedf2106532e1a5d90c63dac18e501f` |
| execution/final inventory | `88c4d686118e5565f92688c7144baaa8e95e7f24b8517b5167228a5b3317f49e` | `0c2a4d340e7740f322a8c2e1be2dfef4d97a03544b12327600f42eb10bf73854` |
| runtime preparation | `6b0cb9ea4e21f18ad6ca53b57cf1892c385d9d4c2944902aeb16366fc654d705` | `2df6457ff883ec100d8095a545d46c07593e53a4d1c336ec41983937daa240c0` |
| command-image probe | `fd92636873c5c1cc9fb280e9a4a475c4defc634e6a8cfe83a0dc98410a7f3845` | `97f047f981c93db57fe6e1a368094c6495926a84dd92238cc168738257042ab4` |
| Harness initialization | `de1cd261cdb3a146ae27611760c98ef5a0d77af256610a180d7501c05c8a0248` | `9fe0352ec36cf7abade481e54c14003e6bb2182a5964c0a025d70e472f9c64fb` |
| socket-cleanup diagnostic | `cb68c266f735e08ed84d23ad2f6704c21dea6c2b7346a43bbc5287a1163d677c` | `cd7cc7d3f2895a1ddfa93e2743fa68689921e9229f63030feb1c920a65bccc9b` |
| DinD cleanup receipt | `aeb3d2c4cbe74e18443dea10bedcdcaac23528f4e4aa2c055ca1cb9e644be67e` | `52dc34a2105f33a6306d9e2e6f1372195ce5e323dc58fe8ad78592d824f57545` |

The report records `provider_execution_authorized=false`,
`provider_execution_scaffold_published=true`, `provider_request_started=false`,
`provider_calls=0`, and `model_process_count=0`. The contract binds the successor to one reopen,
requires the independent v149 audit, and preserves all collection and training flags as false.

## Five-task qualification and image inventory

All five archives were imported through the explicit v148 nested Unix socket without registry
access or partial input. Each official verifier ran with `network=none`, a 900-second test bound,
and a separate 300-second Docker control bound. Base failures were ordinary test failures rather
than infrastructure failures, and all references passed.

| Task | Base | Reference | Fresh command image | Verifier-control diagnostic hash |
| --- | --- | --- | --- | --- |
| Ibex PR-465 | FAIL | PASS | `sha256:a42cd186ad712f69c409940a763628bead2ec598a8afddc8ff635077bb1ac338` | `95d156b0de653be02cfbcd539d8f132aa2de179be4b16f7c41b1690d491f0a44` |
| Ibex PR-1135 | FAIL | PASS | `sha256:515a5b66b4aae2249d33b5c7c85884cb68b12fa7738d9d213839763c2add90f7` | `8549146a517fdb7027ffd95a8b8083d07938108faecb216b15dfc8d424fb974d` |
| Ibex PR-1780 | FAIL | PASS | `sha256:bb0afff7330766710493174315c93f940c16ed7b01738356f8b6865ee78a0081` | `43491811f03d762edd3e9cc70a50a5e7c4d3c4236bc5de0e522e5a320136fdb5` |
| CVA6 PR-2017 | FAIL | PASS | `sha256:3647c22f39c241843374139462234195058ed493121654ababa080f712f0988f` | `c54c23ac8eb2aebdb7593ac4d45dc14d182de309baf75c9b3c344e650c6ac89e` |
| CVA6 PR-2711 | FAIL | PASS | `sha256:e8e8fd975b126b66ba923113da953ef9224eb99c77b5fce5ca410104a02a6b81` | `a1482f5833c0a2877a2c9cc1ffd6d6bb8fdff07d73812429739069248d4cb6f8` |

The fresh inventory contains the controller, workspace runtime, five official verifier images,
and five fresh task-specific command images as its exact required set of 12. Five additional
unrequired intermediate build images make the observed count 17. Every command image passed the
v2 scan: no credentials or Codex, `network=none`, read-only root, non-root identity, all
capabilities dropped, `no-new-privileges`, private IPC/PID namespaces, bounded resources, one
workspace mount, and locked tool hashes. The bounded command-image probe passed for all five tasks.

`DockerRuntime.prepare()` and cleanup passed for all five tasks against the same explicitly bound
nested daemon. The synthetic Harness initialization passed on the temporary internal
`verigym-hwe-net` network while the outer DinD container remained at `network=none`; the temporary
network was removed and the final inner container and volume inventories were empty.

## Cleanup and retained resource disposition

The outer DinD sidecar was removed. The v148-specific cleanup implementation checked the exact
current manifest volume, owner label, and `/data2` socket backing before acting. Its bounded helper
completed with no stdout or stderr, the socket volume was removed, and the socket backing was
restored to owner mode `0700` and is empty. This closes the deterministic v146 predecessor-literal
defect.

Exactly one v148 Docker volume remains:
`verigym-deepseek-harness-v148-dind-data`, labelled with owner
`deepseek-harness-hwe-v148-cleanup-identity-scaffold-v1` and role `data`, bind-backed by
`/data2/jiadongzhu/docker/deepseek-harness-hwe-v148/data`. No container uses it. The retained data
volume was not mounted or opened during this audit. The v142 and v146 volumes were neither
inspected nor mutated. The empty v148 control, runtime, and socket directories remain mode `0700`.

The v148 evidence tree and retained data volume are now frozen. They must not be retried, deleted,
mounted by an unrelated identity, or rewritten. Only the exact v150 successor may reopen the data
volume, once, after its own authorization is merged and the post-merge `main` gate is green.

## Successor boundary

V148 must never be rerun. V149 is only an independent result audit. After this audit is merged and
all eight post-merge `main` Actions classes pass, a fresh v150 authorization may freeze the official
DeepSeek v4 Flash matrix without changing the v148 task, source, image, toolchain, prompt, six-tool,
or provider-boundary locks.

The v150 matrix must use the planned seed/sample `502/18`, execute the five tasks strictly in the
frozen order, enforce the planned provider consumption and bounded-continuation policy, and keep
formal collection and SFT training closed. Provider credentials may exist only in the execution
window and must never be printed, persisted, or hashed. Any scaffold, infrastructure, or security
failure before the provider marker stops without task consumption; any such failure after the
marker consumes the current task and stops.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
