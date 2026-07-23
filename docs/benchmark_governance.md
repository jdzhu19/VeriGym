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
