## Behavior change

Describe what changed and why. Link the relevant issue or design decision when one exists.

## Contract and security impact

- [ ] Persistent schemas or artifact formats are unchanged, or regenerated and documented.
- [ ] Runtime isolation, hidden assets, credentials, and commercial-tool boundaries were reviewed.
- [ ] CLI, configuration, trace, report, and plugin changes include corresponding docs/examples.

## Validation

List the exact commands run, including any explicitly enabled Docker, RTL-tool, or external-suite
checks. Ordinary validation should include:

```text
ruff check .
ruff format --check .
mypy --strict src/verigym
mypy --strict integrations/verigym-codex-cli/src/verigym_codex_cli
pytest
```
