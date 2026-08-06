# VeriGym evaluation campaign

- Campaign: `campaign-d3c7e6df55399bce`
- Name: real-rtllm-commercial-toolchain-campaign-smoke
- Inputs: 3
- Reporting model/tool calls: 0/0
- Complete chat/agent/evolving matrix: yes

## Evaluation matrix

| Input | Mode | Suite | System/version | Model | Resolved | pass@1 | Tokens | Tools | Wall s |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| rtllm-deepseek-agent | agent | rtllm | deepseek-v4-flash-react | DeepSeek/deepseek-v4-flash | 1/1 (100.00%) | 100.00% | 11706 | 3 | 138.169162511 |
| rtllm-deepseek-chat | chat | rtllm | deepseek-v4-flash-chat | DeepSeek/deepseek-v4-flash | 1/1 (100.00%) | 100.00% | 2043 | 0 | 125.046026477 |
| toy-evolving-control | evolving_agent | toy-rtl | campaign-v0 | none | 3/3 (100.00%) | 100.00% | 0 | 0 | 0.0596913173334 |
| toy-evolving-control | evolving_agent | toy-rtl | campaign-v1 | none | 3/3 (100.00%) | 100.00% | 0 | 0 | 0.0590247146668 |

## Exact PPA compatibility partitions

Only rows with the same comparison_partition_id are comparable; profile, task, correctness, runtime, units, constraints, and reference identities remain partitioned. The campaign never ranks different partitions.

| Input/version | Partition | Task | Eligible | Area cand/ref | Delay cand/ref | WNS cand/ref | Ratios A/D |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| rtllm-deepseek-agent/- | `cf70ac24a484bdce` | rtllm/counter_12 | 1 | 153.8976/153.8976 um^2 | 0.810319/0.810319 ns | 0/0 ns | 1/1 |
| rtllm-deepseek-chat/- | `cf70ac24a484bdce` | rtllm/counter_12 | 1 | 153.8976/153.8976 um^2 | 0.810319/0.810319 ns | 0/0 ns | 1/1 |

## Warnings

- rtllm-deepseek-agent: Model cost is missing for 1 resolved run(s).
- rtllm-deepseek-agent: Resolved-run efficiency values are missing for: cli_process_wall_time_s, external_cli_process_wall_time_s, external_command_count, external_input_tokens, external_output_tokens, external_tool_call_count, external_total_tokens.
- rtllm-deepseek-chat: Model cost is missing for 1 resolved run(s).
- rtllm-deepseek-chat: Resolved-run efficiency values are missing for: cli_process_wall_time_s, external_cli_process_wall_time_s, external_command_count, external_input_tokens, external_output_tokens, external_tool_call_count, external_total_tokens.
- toy-evolving-control: Model cost is missing for 6 resolved run(s).
- toy-evolving-control: Resolved-run efficiency values are missing for: cli_process_wall_time_s, external_cli_process_wall_time_s, external_command_count, external_input_tokens, external_output_tokens, external_tool_call_count, external_total_tokens.
- toy-evolving-control: The before/after result is a bounded first-party Evolve-Context pilot and does not establish general performance improvement.
