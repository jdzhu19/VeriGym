# Open RTL GHCR publication audit v1

Date: 2026-09-05

Two redistribution-qualified, open-tool images were published from repository commit
`0b0361804c7130ca245d95d737c028b6321b603c`. They are new `r1` identities; no historical image
tag or benchmark result was replaced.

| Package | Release tag | Immutable OCI index digest |
| --- | --- | --- |
| `ghcr.io/jdzhu19/verigym-rtl-iverilog` | `12.0-r1` | `sha256:44d5e56dc4ecede0aa9b53fd1dc63b2bdfb153b140084ace6b4847edbb673269` |
| `ghcr.io/jdzhu19/verigym-open-rtl-tools` | `iverilog12-yosys067-opensta310-r1` | `sha256:e0398c5c9a8a4c3f838750a79edc678993c5a6e3cc049cc5f7aa1e2fc5413a9b` |

The [publication run](https://github.com/jdzhu19/VeriGym/actions/runs/33941891591) completed
successfully. Each matrix job built `linux/amd64` from the checked-out commit, pushed once, pulled
the published digest, and verified its OCI index. Both indexes contain an amd64 image manifest and
an attestation manifest. The attestation predicates include SPDX SBOM and provenance records.

The pulled artifacts passed the following restricted smoke contract:

- runtime UID/GID `10001:10001`, read-only root, no network, all capabilities dropped, and
  `no-new-privileges`;
- expected Icarus 12, Yosys 0.67, and OpenSTA 3.1.0 tool identities, as applicable;
- only the fixed `PATH` runtime environment entry;
- source-repository and exact-revision OCI labels;
- no credential or commercial-license marker in the image history;
- bundled license text and corresponding fixed source archives for statically built tools.

Anonymous GitHub package-page requests and anonymous GHCR bearer-token manifest requests both
returned HTTP 200 for both tags. The manifest responses returned the OCI index digests recorded
above, so the packages are public and anonymously pullable. Package pages:

- [verigym-rtl-iverilog](https://github.com/users/jdzhu19/packages/container/package/verigym-rtl-iverilog)
- [verigym-open-rtl-tools](https://github.com/users/jdzhu19/packages/container/package/verigym-open-rtl-tools)

Publication uses only repository read and package write permissions, pins third-party Actions by
full commit SHA, and refuses to overwrite an existing release tag. The base image is digest-pinned;
the upstream tool source inputs are fixed by commit or checksummed release archive. The Icarus-only
image carries the exact Icarus source archive and license. The combined image carries the exact
Icarus, Yosys, CUDD, and OpenSTA source archives and their license files.

The Codex agent image was deliberately excluded pending a separate redistribution and dependency
closure review. Commercial EDA binaries, license configuration, MCP site profiles, hidden tests,
datasets, trajectories, and credentials were not published.

Local prepublication builds stopped before producing an image because the host root/containerd
filesystem had no free blocks. The one container created by that failed attempt was removed by
exact ID; no daemon restart, broad cleanup, or user image deletion was performed. GitHub-hosted
build, pull, and runtime verification therefore provide the publication qualification evidence for
these two artifacts.

Repository quality, formatting, and the four publication-contract unit tests passed. The separate
ordinary-test workflow failed on all Python versions at a pre-existing test that hard-codes a
machine-local `/data` scratch path unavailable on GitHub runners; the publication commit does not
change that test. The release workflow itself and its security gates passed. GitHub also warned
that three pinned Actions still declare the deprecated Node 20 runtime and were forced onto Node
24; updating those pins is a maintenance item, not a publication failure.

This is an artifact publication and runtime qualification record only. It is not a benchmark score
or a claim that the images establish functional completeness for a corpus.
