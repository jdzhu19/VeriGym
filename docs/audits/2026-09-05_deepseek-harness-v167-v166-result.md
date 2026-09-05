# DeepSeek Harness v167 audit of the v166 official matrix

Date: 2026-09-05

## Decision

The single authorized execution of `deepseek-harness-hwe-v166-official-matrix-v1` is consumed and
must not be rerun. It stopped fail closed on the first scheduled task, Ibex PR-465, with
`stop_reason=pre_provider_infrastructure_failure`. The provider marker remained `not_started`, so
the run consumed zero provider episodes, zero provider calls, zero provider tokens, and zero task
provider budget. PR-1135, PR-1780, PR-2017, and PR-2711 were not attempted.

No trajectory or candidate dataset was created or admitted. Both
`trajectory_collection_migratable` and `sft_path_migratable` are false, and the result is not a
benchmark score. Formal collection, ordinary collection, SFT, and production training remain
closed.

The failure is again localized to the Harness controller-initialization boundary after the five
task runtime prepares. V164 passed that boundary with synthetic provider values, while v166 used
the two real provider values selected by its launcher. The sanitized v166 result records only
`RuntimeError`; it does not retain the structured helper error, stderr, a raw exception, or a
provider value. This audit therefore does not claim that credentials, endpoint syntax, provider
reachability, or any other individual difference is the cause.

A successor may separately authorize one provider-free diagnostic that gives the real two-name
provider configuration to Harness in `initialize` mode only and persists only a bounded structured
error category. It must hard-fail if a first-request marker appears, omit every task and verifier
run, preserve provider values only in child process memory, and use a fresh identity and fresh
socket/control/runtime/output paths. This audit does not itself authorize that diagnostic, a
provider-bearing retry, or collection.

## Implementation and execution gates

- v166 implementation commit: `1e13a63b00675a24848cb63ede4c5c9c15f60ce0`
- v166 authorization merge/source commit:
  `bae749df3945ca4eb9b1a41d6916afee54ae733b`
- v166 pull request: [#192](https://github.com/jdzhu19/VeriGym/pull/192)
- branch-push run `33972065522`: eight of eight job classes passed
- pull-request run `33972068805`: eight of eight job classes passed
- post-merge `main` run `33972331536`: the first attempt failed only in an unrelated fake-Codex
  repository-agent Docker test that had passed in both pre-merge runs. That failed job was rerun
  once and passed; the final run state is eight of eight successful job classes on the exact merge.
- manifest file SHA-256:
  `e1efc66fa18b3a809533b1dfc40c446687058a6891bbdecf61774d261e44b64d`
- manifest canonical hash:
  `18b9c5fa89bd81b2cfad4ed9f573d239088c7fbb243b938e82ab44d8156e722b`
- runner SHA-256:
  `1b2e421905abf7e41047a98ef05d5a9ba4137b54f62c3530b1515943edcea6f2`
- launcher SHA-256:
  `f0aac83b2dbe2c9c2efb1037483d7796855c02b3f703f434715821963861f948`
- authorization SHA-256:
  `9a1e116191c7cadb249ef735ae0fba69b023f2b94072f7a5ba3e128549450424`

The launcher was invoked exactly once from clean, merged, up-to-date `main` after the post-merge
run reached its final successful state. It selected environment entries by name before reading
their values, removed the frozen aliases and Docker endpoint variables, and restored only the two
DeepSeek names required by the child. No concrete provider or proxy value was printed, persisted,
or hashed.

## Immutable execution evidence

The frozen v166 evidence root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v166-official-matrix-v1`

It contains nine directories including the root, seven regular files, zero symlinks, and no other
filesystem objects. The files total 20,466 bytes. Every directory is mode `0700`; every file is
mode `0600`; all are owned by UID 1004/GID 100. All seven canonical self-hashes validate. Terminal
progress and report are byte-identical. The complete evidence-tree hash is
`e6fac45e18192617574ad2dc524b5a67492056878644f6c0262b6e8d7d526b34`.

The execution-time value scan compared the two distinct nonempty provider values with all seven
files in memory without printing, persisting, or hashing the values and found zero matches.

| Evidence | File SHA-256 | Canonical hash |
| --- | --- | --- |
| PR-465 attempt | `f0ef5599280ec6e2ddc9649c360da5c4024b977d27a8bffd34e846f9e792a255` | `314181510c54690cc3d52910d298baa3e5d41fde61526dcb40d8018171bf8365` |
| socket cleanup | `04bf4aeb527282d3f3589e7dc289a1fd82c85ef195c55d3ce1c354b8b54c9ec5` | `0f960f937981a7bd607be019fa29e3ab7b4f66dfa95dc424ebc1d2d32f214dd3` |
| host headroom | `ca1b39ad4986c3866915d926030220f525bce4e44f2893aa4f5741a57c08b8b9` | `1f2b720b69e21cbb97351b3182494432730e3a728519b0b0f724621a4939e709` |
| provider DinD runtime | `bf721d5b1f27b774d7242c11e0f362f6ea0c2567a8ca709a7d37f8a8198e858d` | `1cf331c4d9e4c172fb6b7804230f0433b3c13ceb74c947675b7be204f424b3a2` |
| provider network | `c7238867c5ee0deb7715e5a522d9ef2d946d4132451398ea7aa9baf8173b8f09` | `a5b0bcb6c729661789a85daa5ad54812bc38653d27431467eb1fdb1e83f162ec` |
| report/progress | `3ca9d2572690f3bff2d3cf0a54c9c33d54cc3899a04fbaae7569dd6eb9cc288b` | `5f51f5ba2ee428aabd95a01b0b9de96816dfbcb3818a59ca96c28401689ca75d` |

## Failure boundary

The absolute host-root gate passed before Docker access with 18,893,352,960 free bytes and
25,955,195 free inodes. The retained v158 data volume reopened exactly once in v166. The runtime
receipt validates the exact `/data2` bind backing, VFS driver, `runc`, host/inner inode equality,
and absence of task layers from the host Docker root. The provider bridge was created and
validated; task and verifier networking remained fixed to `none`.

Five explicit runtime prepares occur before the Harness initialization call. The empty preflight,
task, scan, trajectory, and candidate-dataset directories exist, but
`preflight/zero-provider-preflight.json` does not. There is no task run directory, transcript,
decision row, candidate change, verifier result, or provider marker. The only attempt is PR-465,
recorded as `infrastructure_failure` with all six planes false,
`first_effective_modification_action=null`, `exact_64k_eligible=false`, and
`provider_consumed=false`.

The v164 synthetic diagnostic passing and the real-value v166 initialization failing narrow the
difference set, but do not identify a root cause. The unrecorded structured helper category is the
remaining diagnostic gap. Repeating v166 would violate its one-use authorization and would not
repair that observability gap.

## Cleanup and successor boundary

The v166 sidecar, Harness controller, and inner bridge were removed. The owner-bound v166 socket
volume no longer exists. Its backing directory and the v166 control and runtime roots are empty,
mode `0700`, and owned by UID/GID 1004:100. No container uses the retained v158 data volume.

The terminal report's cumulative v158 data-volume reopen count is three: v162, v164, and v166 each
opened it once. The per-runtime v166 receipt's count of one is local to that execution and must not
be relabeled as the cumulative value. V166 may never reopen the volume again. Any successor that
reuses it must explicitly bind the cumulative count of three and independently authorize exactly
one additional reopen; otherwise it must use a new bind backing and rematerialize only from locked,
complete local archives.

The following values remain false throughout this audit:
`formal_collection_allowed=false`, `formal_collection_started=false`,
`collection_started=false`, `training_started=false`, and
`production_training_ready=false`.
