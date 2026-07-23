# Public Python API

`verigym.api` is the supported MVP facade. It exposes the single-run service, sampling, replay,
experiment planning/execution, and offline reporting without requiring callers to import CLI
implementation modules.

```python
from pathlib import Path
from verigym.api import RunConfig, VeriGym, replay_run

result = VeriGym().run(
    RunConfig(
        task_id="toy-rtl/and-gate-basic",
        agent="scripted",
        output=Path("runs"),
    )
)
assert result.scorecard.resolved
assert replay_run(result.run_dir).scorecard.resolved
```

[`examples/python_api_mvp.py`](../examples/python_api_mvp.py) executes a toy run, model-free
replay, independent sampling with canonical pass@k, a one-child frozen experiment, and report
regeneration. Installed-wheel conformance runs that file from outside the repository import path.

The API does not guarantee stability for arbitrary internal modules. Callers should persist the
returned versioned artifacts rather than Python object pickles. `LocalRuntime` is trusted-host
development execution; select Docker explicitly for the documented containment profile.
