# Local Exchange Calendar Snapshots

The checked-in `sse.yaml` and `szse.yaml` bundles contain one annual snapshot
per year. Each records official closure notice URLs, captured SHA-256 values,
publication dates, and explicit weekday closure dates. The application expands
weekday sessions from that local closure set; it never infers sessions from ETF
price data.

The ingestion CLI refuses any year without a local snapshot. It never infers a
calendar from ETF price data or silently substitutes a third-party calendar.

Before an ETF ingest, run `quant calendar capture-sources` with explicit network
permission. It stores the official notice bodies under the ignored,
content-addressed `data/raw/calendar_sources/` tree. Ingestion refuses to use a
calendar when those local source archives are absent or their hashes differ.
