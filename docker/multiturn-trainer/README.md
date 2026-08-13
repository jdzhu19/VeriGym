# VeriGym multi-turn trainer image

This image freezes the GPU-side Qwen SFT software stack without embedding models, datasets,
adapters, experiment outputs, credentials, or a Docker socket. Its base must be the immutable
image ID produced by `docker/vllm-service-cu129`; the build script additionally seals rLLM commit
`1d1109a655e291b3001d8526d7c9ecc5b9328226`, veRL `0.8.0`, and the selected clean VeriGym
commit into image labels.

The locally verified vLLM 0.22.1+cu129 image is reused as a CUDA/PyTorch layer and as the separately launched model-service
image. The SFT process does not use vLLM. Its Python package, LMCache, OpenCV, and CuPy are removed
from the trainer layer before veRL is installed because veRL 0.8.0 requires NumPy 1.x while the
vLLM 0.22.1 service stack requires NumPy 2.x. Keeping model serving and SFT in separate interpreters
lets both environments pass their own dependency checks. The trainer binds the external service
version in its environment and report; the build still verifies the exact vLLM package before
deriving the trainer layer.

Build with `scripts/build_multiturn_trainer_image.sh`. Run only through
`scripts/run_multiturn_sft_container.sh`, which requires an immutable image ID, four explicit
LSF-assigned GPU indices, read-only model/dataset mounts, a dedicated writable cache/output,
`--network none`, and a synthetic empty home mount. Docker sockets and real home directories are
not mounted.
