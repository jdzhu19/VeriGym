# VeriGym RTL-Repo adapter

This optional distribution adapts the official
[RTL-Repo](https://github.com/AUCOHL/RTL-Repo) Hugging Face Parquet layout to VeriGym. It keeps
the benchmark's repository-context, next-line-completion prompt and reports its native Exact
Match and Edit Similarity metrics. Both ChatEval and AgentEval use the same single-line candidate
contract. It does not turn RTL-Repo into a compile or simulation task.

The separate `official-parquet-v1-agent-eval-v1` variant exposes a browsable read-only
official-context projection. It does not expose `next_line`, load `all_code`, or claim that the
projection is a complete repository; only `repository/completion.txt` is editable.

The independently versioned `official-parquet-v1-agent-eval-v2` projection preserves every v1
context snippet in official order and adds UTF-8 byte counts plus a frozen source/generated path
classification to `repository/context/index.json`. The task directs the agent to the cropped
target tail and source-priority context first. It retains the same hidden target and official
scorer, but has distinct suite, source, task, and configuration identities.

Install from the VeriGym checkout:

```bash
python -m pip install -e ./integrations/verigym-rtl-repo
```

Supply a local snapshot containing `data/train-*.parquet` and `data/test-*.parquet`; the adapter
does not download data or access the network. See `docs/rtl_repo.md` in the main repository for
source preparation and smoke-test commands.
