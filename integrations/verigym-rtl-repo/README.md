# VeriGym RTL-Repo adapter

This optional distribution adapts the official
[RTL-Repo](https://github.com/AUCOHL/RTL-Repo) Hugging Face Parquet layout to VeriGym. It keeps
the benchmark's repository-context, next-line-completion prompt and reports its native Exact
Match and Edit Similarity metrics. It does not turn RTL-Repo into a compile or simulation task.

Install from the VeriGym checkout:

```bash
python -m pip install -e ./integrations/verigym-rtl-repo
```

Supply a local snapshot containing `data/train-*.parquet` and `data/test-*.parquet`; the adapter
does not download data or access the network. See `docs/rtl_repo.md` in the main repository for
source preparation and smoke-test commands.
