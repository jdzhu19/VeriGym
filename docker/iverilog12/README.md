# VeriGym Icarus 12 reference image

This explicit, multi-stage build compiles the real upstream Icarus Verilog `v12_0` tag and
copies only its installed runtime plus minimal libraries, POSIX utilities, and Python for bounded
DockerRuntime control tests. The runtime user is fixed at numeric UID/GID `10001:10001`.

Build it explicitly from the repository root:

```bash
docker build \
  -f docker/iverilog12/Dockerfile \
  -t verigym/rtl-iverilog:12.0 \
  docker/iverilog12
```

The tag is only a request-time convenience. VeriGym inspects it once, records the actual immutable
image ID, and creates every episode container from that ID. The Dockerfile does not assert a base
image digest or source checksum. DockerRuntime records the actual `iverilog -V` and `vvp -V`
results from the built image and derives compatibility from those results.
