# Benchmark governance

VeriGym distinguishes redistributable first-party fixtures from user-supplied third-party data.
The toy RTL suite, synthetic VerilogEval-shaped test fixture, and plugin-conformance task are
small first-party assets with explicit licenses. They test mechanics and are not benchmark
claims.

VerilogEval is never cloned, downloaded, modified, or bundled by VeriGym. Users provide a path
and variant; the adapter validates it read-only and records a content/source identity. Prompts,
references, and tests remain separated, and release evidence records identities rather than
corpus bytes.

Adding or updating a benchmark requires an explicit license/redistribution review, immutable
version/content identity, source-integrity checks, hidden-data policy, known-good/bad acceptance
cases, and contamination-safe audit fixtures. Evolving releases, repository-level tasks, formal
benchmarks, and new benchmark families are deferred beyond the MVP.

## Infrastructure-successor discipline

Before authorizing a successor to an infrastructure-invalid campaign, reproduce the failure with
the same public, frozen inputs when possible. Review the upstream project's official documentation,
release workflow, verification utility, tests, and relevant issue history. Record primary-source
links in the authorization audit and prefer the producer's supported verification path over a
local format assumption.

A successor preserves the stopped identity and starts with a new version. It must add bounded,
content-free stage receipts and prove the repair with an offline regression before consuming
another candidate, provider call, or accelerator allocation. A stage receipt may retain an exit
code, output byte counts, a stderr-presence bit, effective-control hashes, and cleanup state; it
must not persist raw command output, exception text, credentials, proxy values, hidden data, or
task content. If a required upstream verification step needs network access, its official source,
purpose, process identity, scratch lifetime, and credential boundary must be explicit in the new
authorization.
