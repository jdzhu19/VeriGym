# DeepSeek Harness v137 audit of the v136 command-runtime diagnostic

Date: 2026-09-04

## Decision

The single authorized execution of
`deepseek-harness-hwe-v136-command-runtime-diagnostic-v1` is consumed and stopped fail-closed.
It validated the frozen predecessor evidence and completed local PR-465 archive, started one fresh
networkless DinD, and transferred the trusted workspace-runtime image. It then stopped inside the
bounded PR-465 task-image import operation before writing the import receipt or building the
command image. The terminal status is `stopped_after_zero_provider_diagnostic`, the stop reason is
`unexpected_controller_failure`, and the report canonical hash is
`e358b0e2023e81fb7f56ed5b4df0116a3fdf42ac8b0573df7e7b6d455ecad673`.

V136 did not reach either planned runtime-preparation probe. It therefore neither confirms nor
refutes the suspected v134 missing explicit nested-Docker endpoint binding. The failure is a new
zero-provider scaffold failure, not a model or verifier result. No task execution, base/reference
verification, Harness controller, provider request, trajectory, collection, or training started.

## Implementation and merge gates

- v136 implementation commit: `f1dbd527636f3b109dbbae87c26dcd25c13a36c3`
- v136 authorization merge/source commit: `1801d64a965a083d3d156d3598d3a4fa4672a5e1`
- v136 pull request: [#162](https://github.com/jdzhu19/VeriGym/pull/162)
- v136 branch-push run: `33858514064`, eight of eight jobs passed
- v136 pull-request run: `33858518470`, eight of eight jobs passed
- v136 post-merge `main` run: `33858934056`, eight of eight jobs passed
- v136 manifest file SHA-256:
  `5ce70387aec85f4a9cf75a72139e56574c46cbd1d59a9589fc086cc5e47bfc67`
- v136 manifest canonical hash:
  `eb277948d452225f105185e2d919767e1369ede7e4c95f04a03a2e9809de0f3c`
- v136 runner SHA-256:
  `07b2e63529fad93f3075c6d22694754d788a905f0820bb1ad0da43a3f033ce17`
- v136 authorization SHA-256:
  `4278d9c56919014f5a2a1d805ff16c0cc8100ec183bc0a3a83b0e931f52c9825`

The first command invocation rejected the ambient provider configuration before creating its
output root or any Docker resource. That rejection did not consume the one-start allowance. The
authorized invocation removed all frozen provider variable names from its child environment and
used only the merged `main` source after the exact post-merge gate.

## Immutable execution evidence

The immutable evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v136-command-runtime-diagnostic-v1`

It contains six directories including the root, nine regular JSON files, and zero symlinks. Every
directory is mode `0700`; every file is mode `0600`. All schema-defined top-level canonical
self-hashes validate, and the atomic progress and terminal report are byte-for-byte equal.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| report/progress | `71b56c85ac0f036ee313acd42038034e72c072bc619353cec4c79d4e520d1172` | `e358b0e2023e81fb7f56ed5b4df0116a3fdf42ac8b0573df7e7b6d455ecad673` |
| predecessor preflight | `5e8896769e6cea960888b71f10fafe7962069b5e25f7851c1bf374ebcfe70dc3` | `28558f05e31cec7b2346a7ffb77bba4afbd38636a9ab3ed9ca777317ce039a83` |
| PR-465 archive | `21d5ae1c122d933237f3d5d1e27b18a5656509eeb6873f820dba60845d5d4516` | `fc1af152a1ba03044119cf9ce230294498303591f65302299502c679be7c9d63` |
| DinD runtime | `3b34d4d3fd978f3c61f6fc72c8d7f85fda1c052b8045f3d9f45d28b648b37c28` | `b488f89af23be7dd21d13de5bb62798e0eee62943d881181b2eca7d70692d717` |
| workspace-runtime transfer | `129c0a7f9124f9e1bce31e8c5c072fdff8ce0e8062c1d91c34176cc43516ec71` | `4f8c54049e0468cad30860f2b4b55acf38477e47cc8e342bf2bd15bff69a8634` |
| cleanup receipt | `770f931f70c8e048fabb5eb3b30b31b50a58a8c78c227b26febb51384b2a5503` | `4eb080dba133c853f18d75660201b6798bad06bde364c848ce42d7b33ef4d80b` |

An independent scan compared the three available nonempty provider values with all nine evidence
files in memory without printing or hashing those values. It found zero matches.

## Failure boundary

The last successful stage was the trusted workspace-runtime transfer. The task-image import
receipt, command build diagnostic, image receipt, v2 security scan, command-image lock, inner
inventory, and two runtime-binding probe receipts do not exist. The runner deliberately persisted
neither raw exception text nor raw Docker output. Its broad final exception handler reduced the
failure to `unexpected_controller_failure`, so this audit cannot safely distinguish a Docker-load
exit, output-policy rejection, image-identity check, tag-binding check, or controller defect.

The completed archive at
`docker-tar-archives/lowrisc_m_ibex/pr-465.tar` remains a regular non-partial file of 473,571,328
bytes whose SHA-256 is
`f92f93032f43f8740e6e070c92b081405e7a624e38b5e48b2cc010ca754f16e0`. Its prior static archive,
OCI manifest/config, and repository bindings passed. Those checks establish input identity, not
that the interrupted v136 import succeeded.

## Cleanup and resource disposition

The v136 cleanup helper exceeded the controller's 300-second wait by roughly nine seconds. The
controller therefore wrote a conservative `cleanup_unconfirmed` receipt while the exact v136
helper remained active. The helper subsequently exited zero. An independent owner/role/options
check then confirmed the exited helper and both bind-backed volumes belonged only to v136, and
removed exactly `verigym-dind-v136-cleanup`,
`verigym-deepseek-harness-v136-dind-data`, and
`verigym-deepseek-harness-v136-dind-socket`.

No v136-labelled container or volume remains. The data backing, socket backing, and runtime
scratch are empty, owned by UID 1004/GID 100, and mode `0700`. This late remediation does not
rewrite or upgrade the immutable v136 cleanup receipt; v136 remains a failed execution.

## Successor boundary

V136 must never be rerun. A successor must use a new identity and fresh `/data2` data/socket
volumes. Before another provider authorization it must materialize all five official-route tasks
from completed local archives, retain a stage-specific allowlisted import failure category without
raw output, and make late-success cleanup observable without converting a timeout into success.
It should transfer/import archives through an explicitly selected nested endpoint and must test
the task command runtime with an explicitly injected `DockerCliEngine` bound to that same endpoint.

The successor may preserve all five tasks as provider-unconsumed. It may not inspect or mutate the
frozen v132 data volume, retry v134 or v136, access a registry or `.partial` archive, contact a
provider, or publish a partial scaffold contract. A new provider matrix still requires a separate
independent result audit, merged authorization, and green post-merge `main` gate.

Formal collection and training remain closed:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
