# VeriGym evaluation campaign

- Campaign: `campaign-9c68cca77d7a031c`
- Name: real-rtllm-deepseek-vcs-dc-platform-campaign-smoke
- Inputs: 3
- Reporting model/tool calls: 0/0
- Complete chat/agent/evolving matrix: yes

## Evaluation matrix

| Input | Mode | Suite | System/version | Model | Resolved | pass@1 | Tokens | Tools | Wall s |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| rtllm-deepseek-agent | agent | rtllm | deepseek-v4-flash-react | DeepSeek/deepseek-v4-flash | 1/1 (100.00%) | 100.00% | 11706 | 3 | 138.169162511 |
| rtllm-deepseek-chat | chat | rtllm | deepseek-v4-flash-chat | DeepSeek/deepseek-v4-flash | 1/1 (100.00%) | 100.00% | 2043 | 0 | 125.046026477 |
| rtllm-deepseek-evolving-agent | evolving_agent | rtllm | deepseek-react-context-v0 | DeepSeek/deepseek-v4-flash | 3/3 (100.00%) | 100.00% | 14848 | 3.66666666667 | 138.645196118 |
| rtllm-deepseek-evolving-agent | evolving_agent | rtllm | deepseek-react-context-v1 | DeepSeek/deepseek-v4-flash | 3/3 (100.00%) | 100.00% | 16354.6666667 | 4 | 129.454237722 |

## Exact PPA compatibility partitions

Only rows with the same comparison_partition_id are comparable; profile, task, correctness, runtime, units, constraints, and reference identities remain partitioned. The campaign never ranks different partitions.

| Input/version | Partition | Task | Eligible | Area cand/ref | Delay cand/ref | WNS cand/ref | Ratios A/D |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| rtllm-deepseek-agent/- | `cf70ac24a484bdce` | rtllm/counter_12 | 1 | 153.8976/153.8976 um^2 | 0.810319/0.810319 ns | 0/0 ns | 1/1 |
| rtllm-deepseek-chat/- | `cf70ac24a484bdce` | rtllm/counter_12 | 1 | 153.8976/153.8976 um^2 | 0.810319/0.810319 ns | 0/0 ns | 1/1 |
| rtllm-deepseek-evolving-agent/deepseek-react-context-v0 | `cf70ac24a484bdce` | rtllm/counter_12 | 3 | 153.8976/153.8976 um^2 | 0.810319/0.810319 ns | 0/0 ns | 1/1 |
| rtllm-deepseek-evolving-agent/deepseek-react-context-v1 | `cf70ac24a484bdce` | rtllm/counter_12 | 3 | 153.8976/153.8976 um^2 | 0.810319/0.810319 ns | 0/0 ns | 1/1 |

## Warnings

- rtllm-deepseek-agent: Model cost is missing for 1 resolved run(s).
- rtllm-deepseek-agent: Resolved-run efficiency values are missing for: cli_process_wall_time_s, external_cli_process_wall_time_s, external_command_count, external_input_tokens, external_output_tokens, external_tool_call_count, external_total_tokens.
- rtllm-deepseek-chat: Model cost is missing for 1 resolved run(s).
- rtllm-deepseek-chat: Resolved-run efficiency values are missing for: cli_process_wall_time_s, external_cli_process_wall_time_s, external_command_count, external_input_tokens, external_output_tokens, external_tool_call_count, external_total_tokens.
- rtllm-deepseek-evolving-agent: Model cost is missing for 6 resolved run(s).
- rtllm-deepseek-evolving-agent: Resolved-run efficiency values are missing for: cli_process_wall_time_s, external_cli_process_wall_time_s, external_command_count, external_input_tokens, external_output_tokens, external_tool_call_count, external_total_tokens.
- rtllm-deepseek-evolving-agent: The before/after result is a bounded first-party Evolve-Context pilot and does not establish general performance improvement.
