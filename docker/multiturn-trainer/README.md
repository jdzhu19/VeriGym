# VeriGym multi-turn trainer image

This image freezes the GPU-side Qwen SFT software stack without embedding models, datasets,
adapters, experiment outputs, credentials, or a Docker socket. Its base must be the immutable
RepoDigest for `vllm/vllm-openai:v0.22.1`; the build script additionally seals rLLM commit
`1d1109a655e291b3001d8526d7c9ecc5b9328226`, veRL `0.8.0`, and the selected clean VeriGym
commit into image labels.

Build with `scripts/build_multiturn_trainer_image.sh`. Run only through
`scripts/run_multiturn_sft_container.sh`, which requires an immutable image ID, four explicit
LSF-assigned GPU indices, read-only model/dataset mounts, a dedicated writable cache/output,
`--network none`, and a synthetic empty home mount. Docker sockets and real home directories are
not mounted.
