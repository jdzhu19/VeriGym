# VeriGym open RTL tools with OpenSTA

This independent image recipe extends the frozen Icarus 12 and Yosys 0.67 toolchain with
OpenSTA 3.1.0. It does not replace the accepted `iverilog12-yosys067` image or tag. All downloaded
source archives are checked against the hashes in `SOURCE_IDENTITIES`, and VeriGym resolves and
records the final local image ID before use. Public-distribution builds also retain the exact
source archives and the Icarus, Yosys, OpenSTA, and CUDD license texts in the final image.

Build only by explicit operator action from the repository root and through the qualified
user-defined bridge:

```bash
docker build \
  --network verigym-hwe-net \
  -f docker/open-rtl-tools-opensta/Dockerfile \
  -t verigym/open-rtl-tools:iverilog12-yosys067-opensta310-r1 \
  docker/open-rtl-tools-opensta
```

Benchmark, agent-workspace, synthesis, and verifier sessions still use `network=none`; the bridge
above is only for the controlled image build. The image uses non-root UID/GID `10001:10001` and
contains no PDK, SDC, benchmark source, credential, or commercial asset.

The `-r1` suffix is a new public-distribution identity. It does not replace the frozen local
`iverilog12-yosys067-opensta310` tag or any historical profile that binds that image ID.
