# Cross-mode evaluation campaigns

A campaign is an offline projection over completed, immutable VeriGym experiments. It combines
ChatEval, AgentEval, and EvolvingAgentEval results without rerunning a model, agent, verifier,
runtime, Docker daemon, commercial tool, or network request. Campaigns do not replace experiment
planning: run each track independently, then bind its frozen artifacts in one campaign config.

Start from
[`examples/campaigns/rtllm-platform-matrix.example.yaml`](../examples/campaigns/rtllm-platform-matrix.example.yaml):

```bash
verigym campaign validate --config campaign.yaml
verigym campaign generate --config campaign.yaml
```

Paths are resolved relative to the config file and may not traverse symlinks or `..`. Ordinary
`experiment` inputs must declare `chat` or `agent` and contain exactly one frozen system. An
`evolving_evaluation` input binds both the held-out experiment root and its independently validated
`evolving-evaluation.json`. Its v0/v1 plans must match on task/sample sets, model configuration,
runtime, prompt/tool policy, verifier, correctness definition, budgets, and resolved synthesis
profile. Only explicit agent-version identity and bounded memory options may differ.

Generation writes three deterministic artifacts:

- `campaign_report.json`: authoritative versioned identities and metrics;
- `campaign_report.csv`: evaluation rows plus exact PPA-partition rows;
- `campaign_report.md`: a paper-oriented capability and result matrix.

Correctness always retains explicit planned/evaluable/resolved denominators. License failures stay
in verifier/tool infrastructure accounting and are never converted into model failures. Cost is
summed only inside one explicit currency or provider-unit partition.

## PPA comparison boundary

Every quality row preserves the existing exact compatibility partition over suite source, task,
correctness, declared and resolved profiles, runtime/image, units, constraints, clock period, and
reference candidate. Rows are comparable only when `comparison_partition_id` is identical. A
campaign never pools or ranks different partitions, so results from different DC libraries,
constraints, tool versions, or open-source profiles remain visibly separate.
