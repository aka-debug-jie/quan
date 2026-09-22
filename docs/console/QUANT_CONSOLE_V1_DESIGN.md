# Quant Console V1 design

Status: implemented local read-only application design.

The console normalizes four approved structured source families into one
content-addressed application snapshot: Historical V3, Quant Upgrade V1, the
V2 closure manifest, and RC-02 published prospective JSON. Markdown remains
explanatory material and is never the sole metric authority.

The Upgrade adapter selects the final 51 runs from the frozen matrix. The 19
unreferenced pre-fix artifacts remain `INVALID_ENGINEERING` evidence and are
excluded from current counts. Run evaluability, matched-benchmark
comparability, economic outcome, engineering state, prospective input phase,
and system freshness are independent fields.

The web process reads only the current normalized snapshot. Explicit reload
parses only configured source roots and atomically swaps `current.json`; a
failed reload retains the prior view. Systemd observation is a separate
fixed-target CLI action. No HTTP request imports or invokes a runner, broker,
provider, SQLite account, systemctl, shell command, or network data adapter.

The application binds to `127.0.0.1`, serves API and static assets from one
origin, validates Host and Origin, and exposes only opaque artifact/evidence
IDs. Safe export contains aggregate metrics and hashes, never raw bars,
positions, account databases, absolute paths, or sealed data.
