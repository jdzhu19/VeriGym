# vLLM 0.22.1 CUDA 12.9 service image

This image is the GPU model-serving boundary for Qwen3.5. It uses the upstream vLLM 0.22.1
CUDA 12.9 release wheel because the upstream default CUDA 13 image cannot run on the R525 driver
installed on `gpu01`. The build freezes the Python base RepoDigest, or its exact local image ID on
a compute node whose daemon cannot fetch the digest manifest, and verifies the upstream wheel
SHA256, installed vLLM version, PyTorch version, CUDA variant, and dependency consistency. In both
forms the resolved base image ID is recorded in the service image label.

Models, caches, credentials, experiment outputs, source trees, and Docker sockets are not embedded.
Build with `scripts/build_vllm_service_image.sh`. Run with
`scripts/run_vllm_service_container.sh`, which requires an exact image ID, four LSF-assigned GPU
indices, a read-only model mount, a dedicated cache, a synthetic empty home, and an existing
user-defined bridge. It publishes the API only on host loopback for colocated OpenHands/rLLM
clients. It never uses `--privileged`, host IPC, the default Docker bridge, or a Docker socket.

Pass `-` as `ADAPTER_ROOT_OR_DASH` and repeat the base identity as `SERVED_MODEL_ID` for a base
service. For the development adapter run, pass the read-only adapter directory and a distinct
served identity; the runner enables vLLM LoRA serving without copying adapter bytes into the image.
