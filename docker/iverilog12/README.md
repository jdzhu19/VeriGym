# VeriGym Icarus 12 reference image

This explicit, multi-stage build compiles the real upstream Icarus Verilog `v12_0` peeled commit and
copies only its installed runtime plus minimal libraries, POSIX utilities, and Python for bounded
DockerRuntime control tests. The runtime user is fixed at numeric UID/GID `10001:10001`. The base
image is digest-pinned. The final image includes Icarus's GPLv2 license and a corresponding source
archive for the exact compiled commit.

Build it explicitly from the repository root:

```bash
docker build \
  -f docker/iverilog12/Dockerfile \
  -t verigym/rtl-iverilog:12.0-r1 \
  docker/iverilog12
```

The tag is only a request-time convenience. VeriGym inspects it once, records the actual immutable
image ID, and creates every episode container from that ID. DockerRuntime records the actual
`iverilog -V` and `vvp -V` results from the built image and derives compatibility from those
results. Historical `verigym/rtl-iverilog:12.0` identities remain unchanged; the `-r1` suffix is a
separate public-distribution identity.
