# CN Historical Research V3 runtime

The V3 code worktree, environment, data, ledgers and reports are separate from
the RC-02 prospective deployment:

- code: `external/cn-historical-v3/worktree`
- locked clean environment target: `external/cn-historical-v3/.venv-v3`
- locally validated isolated runtime: `external/cn-historical-v3/runtime-env`
- data: `external/cn-historical-v3/data`
- artifacts: `external/cn-historical-v3/artifacts`

The validated runtime is Python 3.11.15 with h5py 3.15.1, pyarrow 23.0.1,
pandas 3.0.5 and typer 0.27.2. `uv.lock` contains the `v3-historical` group with
h5py 3.15.1 and BaoStock 0.8.9. GitHub CI creates a fresh environment from this
lock and runs the V3 offline fixture suite.

Typical offline validation from the V3 worktree is:

```bash
env PYTHONPATH=src ../runtime-env/bin/python -m pytest \
  --cov=quant_stack --cov=quant_stack_v2 --cov=quant_stack_v3
```

Network capture is never part of tests. The RQAlpha bundle and official action
evidence are immutable local inputs and are not committed or redistributed.
