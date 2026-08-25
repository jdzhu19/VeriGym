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
runtime, version-neutral prompt contract, tool policy, verifier, correctness definition, budgets,
and resolved synthesis profile. Only explicit agent-version identity, the bound prompt-policy
fingerprint, and bounded memory options may differ.

Generation writes three deterministic artifacts:

- `campaign_report.json`: authoritative versioned identities and metrics;
- `campaign_report.csv`: evaluation rows plus exact PPA-partition rows;
- `campaign_report.md`: a paper-oriented capability and result matrix.

See the [all-real evolving campaign smoke](audits/real_evolving_campaign_smoke.md) for the current
DeepSeek + RTLLM + VCS/DC platform example and committed provenance. The earlier
[commercial-toolchain smoke](audits/real_campaign_smoke.md) retains the scripted evolving control
as historical evidence.

Correctness always retains explicit planned/evaluable/resolved denominators. License failures stay
in verifier/tool infrastructure accounting and are never converted into model failures. Cost is
summed only inside one explicit currency or provider-unit partition. Evaluation rows distinguish
the model-client plugin from the frozen provider/model identity. PPA rows retain candidate and
reference medians as well as ratios, with their units and exact comparison partition.

## PPA comparison boundary

Every quality row preserves the existing exact compatibility partition over suite source, task,
correctness, declared and resolved profiles, runtime/image, units, constraints, clock period, and
reference candidate. Area/timing/power partitions preserve candidate and reference power medians,
their ratio, and the power unit without combining power with area or timing. Rows are comparable
only when `comparison_partition_id` is identical. A campaign never pools or ranks different
partitions, so results from different DC libraries, constraints, activity modes, tool versions, or
open-source profiles remain visibly separate.
