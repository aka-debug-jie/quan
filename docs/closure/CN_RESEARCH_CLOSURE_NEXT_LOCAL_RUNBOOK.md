# CN Research Closure Next local runbook

This study and its Console preview use the isolated
`external/cn-research-closure-next/` worktree, Python environments, caches,
artifacts, evidence archive and runtime. The source RQAlpha bundle and the
retained Upgrade V1 artifacts are read-only inputs. The live prospective
worktree and its systemd timer are not installation targets.

Set `QUAN_ROOT` to the existing repository's absolute path and run commands
from `$QUAN_ROOT/external/cn-research-closure-next/worktree`. Python 3.11 and
the checked-in `uv.lock` are required. `uv sync --locked --group v3-historical`
may populate the isolated research environment; Console backend has its own
lock in `apps/quant-console/backend/uv.lock`. Frontend dependencies use the
checked-in `package-lock.json` with Node 20.19.5. The local acceptance report
records the exact environments used on this host.

## Rebuild and validate the research revision

The frozen source identities are in
`configs/closure/cn_research_closure_next_v1.yaml`. Pass the local bundle,
normalized bars, frozen score cache, retained Upgrade V1 matrix, and local
evidence root to `quant-v3 closure preflight`; use the same inputs for
`quant-v3 closure run`. The final action overlay is
`configs/closure/action_evidence_v4.yaml`. No research command enables network
access. Issuer documents were captured separately with explicit, bounded
network commands and retained by SHA-256 in the ignored evidence archive.
Preflight checks all 11 inherited filing bytes as well as the new filings.
Closure runs require a fresh artifact root; prior results are not a restart
cache, and a stopped run must be resumed only as a new revision.

The completed matrix and its base manifest are immutable files below the
isolated artifact revision root. Run
`python -m quant_stack_v3.closure_publication` with `--matrix-path`,
`--manifest-path`, `--action-evidence-path`, `--evidence-root` and
`--artifact-root` to publish a safe evidence index and Console manifest.
Pass `--validated-code-commit` only after committing and validating a clean
worktree at that exact full SHA; otherwise the manifest says
`UNCOMMITTED_UNVALIDATED` and is not the final acceptance artifact.
For one independent no-cache economic reconstruction, run
`python -m quant_stack_v3.closure_rebuild` with a separate `--rebuild-artifacts`
root that is new or empty and a registered `--experiment-id`; a mismatch fails
the command. The independent rebuild accepts the registered diagnostic control
and optional scale run as well as the original 51 experiments.

## Start and stop the local Console preview

Create a new runtime `sources.toml` from
`apps/quant-console/config/sources.example.toml`. Pin `[closure_next]` to the
published manifest and its isolated artifact revision. Keep the Historical V3,
Upgrade V1 and published prospective JSON sources pinned separately. Only this
new runtime is indexed; the stable Console V1.5 runtime is not replaced.

```bash
QUAN_ROOT=/absolute/path/to/quan
CONSOLE_TREE="$QUAN_ROOT/external/cn-research-closure-next/worktree"
CONSOLE_ROOT="$QUAN_ROOT/external/cn-research-closure-next"
mkdir -p "$CONSOLE_ROOT/console-runtime/static"
cp -a "$CONSOLE_TREE/apps/quant-console/frontend/dist/." \
  "$CONSOLE_ROOT/console-runtime/static/"
"$CONSOLE_ROOT/console-python-env/bin/quant-console" observe-system \
  --output "$CONSOLE_ROOT/console-runtime/system-observation.json"
"$CONSOLE_ROOT/console-python-env/bin/quant-console" index \
  --config "$CONSOLE_ROOT/console-runtime/sources.toml" \
  --runtime "$CONSOLE_ROOT/console-runtime"
bash "$CONSOLE_TREE/apps/quant-console/scripts/start-local.sh" \
  "$CONSOLE_ROOT/console-runtime/sources.toml" \
  "$CONSOLE_ROOT/console-runtime" \
  "$CONSOLE_ROOT/console-python-env" \
  "$CONSOLE_ROOT/console-runtime/static" 8767
```

Open `http://127.0.0.1:8767`. Stop with `Ctrl+C` in the launch terminal. The
script does not install a service, bind a public interface, run research,
initialize a paper account or submit an order. Static assets are copied from
the checked local frontend build to the isolated runtime before launch.

Synthetic browser tests use offline fixtures. Real browser acceptance uses
`QUANT_CONSOLE_REAL_URL=http://127.0.0.1:8767` and checks old/new study paths,
source evidence and prospective account separation. Real screenshots and raw
account artifacts remain local and ignored by Git.
