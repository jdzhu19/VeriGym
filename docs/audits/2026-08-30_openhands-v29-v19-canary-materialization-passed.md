# OpenHands v29 materialized the static v19 canary contract

## Result

The one authorized run of `openhands-hwe-v29-v19-canary-materialization-v1` built and independently
security-locked all five public reserve agent images, sealed the five-task v19 qualification
receipt, and materialized the static v19 canary contract. It made zero provider calls and did not
execute the canary.

The authorization merged as PR #34 at commit
`f81a975f242256514fd11fd5aa0876e7c33defa2` after all 16 push/PR results for the eight required
Actions classes passed. Full evidence remains outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v29-v19-canary-materialization-v1`.

The final `materialization-progress.json` has SHA-256
`f2992d89c13de3ce4a55cb15f4c4985be8c7dd2c0402ea1b675bb793f55b00f2`. Its canonical progress
hash is `42f85402c9e509a687ec32c953b24a026f978b5bf0684eb877f32876d0d302f0` and recomputes exactly.
The complete 24-file evidence directory hash is
`d05a89da0cb54a1a18db13214c74b0fe6b50a3aaae10920b2aafc2debbc8f375`.

## Five task-keyed image locks

Every image was built with Dockerfile `RUN` networking set to `none`, then scanned in a distinct
runtime container with `network=none`, a read-only root, non-root UID/GID, cap-drop `ALL`,
no-new-privileges, bounded resources, and only the visible workspace mount. Each verifier source
image and final agent image was addressed by immutable image ID.

- PR-2330: agent image
  `sha256:2a30bdf305d6d81d08e77cdeaaf83cc9dbb90bc544913b5e6c813cd03bbcffd0`, lock
  `e26ca258478f3182d3ebf145ae17451fea22522f74ae5eb4b3c7af5dc4b26036`, security scan
  `887ee94136a8494d4d1ba2e9ffbe11b479b62614e7c42c4ee980760086e72567`.
- PR-3226: agent image
  `sha256:5828376d1dfb2151e08a4839ed557f5394f34cd9c6f2e6846e7e57d4a9918923`, lock
  `71f05955ded644c97d85ec53aafb89fc2675498103a4839a36009a40ec5f0926`, security scan
  `f1d05bb39a079660807645657d5497264ccdcc18469cde380c013608500d7854`.
- PR-3231: agent image
  `sha256:0cf104389b58e2f3448e673f911b8957272cf548046ea044c3030a1d591d90f6`, lock
  `4318625b6d93f680fa4ae19285c28cde504d68965cca17f2b8b0b4a620df4576`, security scan
  `55936551f1b13cd9dd331a715e3e08f1e8d6379cafa53e48f5e6cd79ab826ac8`.
- PR-2989: agent image
  `sha256:54afe78639f3c3f3c5b5c7c61e1229b10fda0e37e00b9b14b4c7b7b6f1964ae1`, lock
  `cae38b4a1cf018929ad14edb8aaea06512c088585ec9560f1cffc315395d027b`, security scan
  `eebe1a46a0f3c27186e5cfb588a5b4f425df4f623c1ee49ded4555e1fcd052a7`.
- PR-3059: agent image
  `sha256:a41b0c87eb322bda05bdbd69a0f300e7effdf1198022650c8701afff7a48aa1a`, lock
  `824c5df9a84b2f91bc545e79930d280fac8d24a2b8cc5d630d88a88f469c772f`, security scan
  `e5e337e6a6de7ab260bdcbb6cd9eeb29ebabdb5e634d14c121a05f142e35db1f`.

The five derived agent image IDs are distinct. No container uses any of the five sanitized or five
scan-only intermediate image IDs, and no materializer build or scan scratch directory remains.
The intermediate images remain local scan evidence and are not selected by any contract binding.

## Receipt and contract chain

The source catalog spans the immutable v26, v27 and v28 source roots without copying them. It has
catalog hash `7d708bb0c7ac86e0562899e42abce671cde0c9c5b1d96fa21420cfed1fed400f`
and file SHA-256 `09abccc6d25f20abd9866d9bd8a7004727566a10bf3aa87af02077637931836a`.
It contains only origin labels, relative source paths and lock hashes; it contains no host absolute
path.

The v19 qualification receipt has canonical hash
`3eea3a1b0fc2bb3d2027c4c9c97549012ce32c484b3b7d07bdb15fc5260e59cb` and file SHA-256
`c56201069b55e1eb1bf5d7532dbfe891d54aa562c2ee980a83e3340f3b05d9e8`.
It preserves the frozen training reserve PR-2330/3226/3231 and validation reserve PR-2989/3059.
Historical transfer or adapter failures remain immutable predecessor evidence and were neither
retried nor relabelled.

The canary contract has canonical hash
`cf6ba5b011f35ec958eaef319ee79ee4f8cd2fcbab77f0dae62f6dbd2c202efc` and file SHA-256
`c65e4f10d243c0efb3e56fb2217c4c65f350cd58cd51aa0f69b13b3f12854a8a`.
It selects exactly PR-2330 training followed by historical PR-3204 validation, seed 489, sample
index 5, DeepSeek v4 Flash, OpenHands 1.42.1, LiteLLM 1.93.0, tiktoken 0.7.0, temperature zero,
zero provider/episode retries, required-tool v19 policy, 64 provider calls, 1,000,000 provider
tokens, 65,536 context tokens and 2,048 output tokens. It permits no fallback identity or
truncation.

## Security and negative claims

An independent post-run scan validated all 24 result files and 57,191 bytes with zero hard secret
leaks and zero scanner errors. The scan explicitly checked active proxy values and the repository,
result, v26, v27 and v28 host paths; none was persisted or hashed. Its report hash is
`ebac8260a52b29536db112b3364b65ef03ce6a8abe76fd6f7eb34b3307c0e9f2`.

Provider calls and model processes remained zero. No held-out task was loaded. The canary was not
executed, no trajectory or decision record was produced, collection and SFT did not start, and no
GPU job or adapter exists. `production_training_ready=false` and `benchmark_score_claimed=false`
remain fixed.

## Next gate

A separate provider-canary runner and authorization must bind this exact contract and pass all
eight Actions classes before the two no-retry episodes may run. Any infrastructure or security
failure must stop immediately; any ordinary benchmark, protocol, exact-trajectory, admission or
64K failure must close this canary without consuming another reserve or creating a new identity.
This result audit authorizes no provider call by itself.
