# External Training Reference Smoke

- Date: 2026-08-09
- Gate: **PASS**
- Scope: interface and reward-oracle capability smoke; no optimizer or weight update was run

## Frozen inputs

The source was the existing one-record real RTLLM training trajectory dataset with dataset hash
`c0f224282d6cd68bdd3e59fd5c752d5f32b02360ad17a936919d373e803e2eb7`. The reference
pipeline selected the eligible `rtllm/up_down_counter` training episode and excluded no records.

The local `Qwen/Qwen3.5-9B` snapshot passed metadata preflight as
`Qwen3_5ForConditionalGeneration` with four safetensors shards totaling 19,306,310,880 bytes.
Its path-free snapshot identity is
`b8e87778e9d98868b0a5c0cd2ba7e1ed07d649362e3ff315f1cbd9b4dc10b477`.

## Results

`prepare` produced a 44 KiB sealed bundle with manifest hash
`8bc5f4bed6ba15642589ae848c2b97a93cce82f5aebf64e5ffb9f914e67372dd`. Independent
offline `validate` replay passed. A scan found no credential values or raw host paths.

The online reward oracle then submitted the previously resolved training candidate through an
ordinary local VeriGym run using VCS 2022.06. The result was infrastructure-valid,
`resolved_candidate`, and `repo_rtl_sparse_v1 = 1.0`, with result hash
`9734a3091eebe1c0c48d9acb6570cb55129966c30dae5420e1f2e7caa4f66aaf`. Hidden assets and
the reference solution were not exported.

This establishes the external handoff and completion-to-verifier-to-reward path. It does not make
a claim about RL convergence or improvement; that requires a separate bounded training campaign
and frozen held-out comparison.
