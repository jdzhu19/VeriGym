# VeriTask intermediate representation

`VeriTask` is the versioned boundary between a suite adapter and the evaluator. It describes a
single task without embedding verifier-only bytes in model-visible fields.

Required identity fields include `id`, suite/version information, interaction modes, editable
paths, required tools, budgets, prompt policy, and a verifier DAG. Public workspace assets and
hidden verifier assets are resolved separately by the suite. The task fingerprint is computed
from canonical JSON and is frozen into run and experiment identities.

Adapters must:

- emit schema version `1.0` and reject unknown fields;
- use normalized relative POSIX paths;
- keep references and hidden tests out of prompts, traces, and public artifacts;
- declare every agent-visible tool and editable path;
- make source validation read-only and deterministic.

Loaders reject unsupported schema versions before constructing a task. See
[`artifact_contract.md`](artifact_contract.md) for persistence rules and
[`adding_a_suite.md`](adding_a_suite.md) for an adapter checklist.
