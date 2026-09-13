# Limited development use v1

This is a separate development-use contract, not an amendment or substitute for
the frozen V2 dataset/experiment contracts. Status: `LIMITED_DEV_RESEARCH`.
Formal qualification stays `BLOCKED_DATA`; CSI500 sealed testing stays
`NOT_STARTED`. No portfolio returns, promotion, execution or live orders follow
from this contract.

## Scope and prerequisites

The complete real-use prerequisite matrix is in `V2_NEXT_02_READINESS.md`.
`configs/v2/development/limited_dev_v1.yaml` and
`configs/v2/models/dev_smoke_v1.yaml` retain missing real definitions as null.
They are requests, not executable approval. No SDK defaults or synthetic dates
fill their blanks. Real export/normalization and real DEV_SMOKE remain disabled.

The executable v1 schema supports **synthetic normalized CSI300 fixtures only**.
It rejects real symbols, real-data tags and CSI500. This provides a complete
testable path while the real Alpha158 fields/processors, warm-up, exact label,
splits, parameters and export authority remain unspecified. It does not claim
to implement a real Qlib archive reader or real Alpha158 assembly.

Each executable scope binds: raw normalized source byte hash; synthetic snapshot
and tree identity; explicit securities, fields, session calendar, source bounds,
train/validation bounds; named causal lag features; an exact forward endpoint
ratio label; maximum warm-up; allowed training/validation label end dates;
embargo; train-only preprocessing; fixed model families, complete parameters and
one seed. The synthetic snapshot/tree is distinct from the real archive/tree.

`forward_ratio` means `value[T+end_offset] / value[T+start_offset] - 1`, with
offsets in the approved session calendar and `end_offset > start_offset >= 1`.
This is an explicit synthetic-engine capability, not an inferred definition of
either formal research track. Feature lags are nonnegative. Warm-up and label
dependency rows are not formal samples. No future missing label or future
membership state can decide prediction eligibility at T.

## Authority and provider-neutral evidence

`UsePins` includes contract, evidence and the expected view identity; all are supplied by the operator/test harness
from a trusted configuration, not by an untrusted run request. The authority
directory and pins are the trust boundary. This v1 does **not** implement a real
approval service, signature/key distribution or privileged exporter deployment.
Someone who controls both authority bytes and trust pins can redefine authority;
the Python API is not an OS privilege boundary.

The new provider-neutral evidence kind is
`independent_source_scope_verification`: provider is provenance metadata only.
`attest_synthetic` opens and validates the actual normalized source before
producing an evidence blob. `load_evidence` reopens hash-named contract and
evidence files, recomputes bytes' SHA-256, validates strict schemas, validator
version, snapshot/tree/source identity, securities, dates, fields and calendar.
The exporter additionally reopens source bytes and verifies actual row/schema
and membership identities. No caller-supplied `QUALIFIED` is accepted.

This migrates the **new development entrypoint** away from a vendor-named gate.
The legacy v1 formal Foundation Gate and old reports are retained for historical
compatibility and are not used to authorize development runs. No legacy
`tushare_raw_reconciliation` report is relabelled as passed, and normalized source
integrity is not falsely called independent real-market price reconciliation.
Formal evidence-validator migration remains separate from this limited path.

## Export and run

`export_view` accepts only bound identities beneath fixed roots: no queries,
callbacks, arbitrary relative files or raw package copy. Reads traverse directory
descriptors with no symlinks, reject hardlinks/devices and bound sizes, and reject
the sealed root before opening it. Output contains only approved symbols,
fields and the union of formal dates, required causal lags and label endpoints.
Missing rows are represented explicitly; T membership selects formal samples,
then their dependencies are retained even when future membership or labels are
missing. A manifest is published only after complete content-addressed data.

`DevBaselineRunner` consumes the fixed use/evidence/view identities through the
loader on every request, including repeated runs. It assembles only the approved
features and labels, fits preprocessing only on eligible training rows, fits
the selected predeclared Linear/LightGBM model, predicts the validation view,
saves/reloads and compares predictions, and persists a separate development
result. Undefined signal metrics use null with limitations, never artificial
zero CAGR/Sharpe/trade counts. Result identity includes all inputs and runner
identity. No entrypoint invokes `run_sealed_baseline_once`.

Blob publication uses Linux `renameat2(RENAME_NOREPLACE)` and is immutable.
Partial writes are not valid blobs;
repeated runs re-fit the same fixed model and must reproduce the original complete
manifest exactly; a no-replace completion pointer detects result drift. Interrupted
runs and failures remain explicit rather than being silently promoted or
overwriting old results. Filesystem guarantees assume the declared POSIX local
store, not arbitrary remote/object-store consistency.

## Approval needed for real use (one batch)

Supply all null fields in the two proposed configs, the approved CSI300
security/date roster and field semantics, a restricted canonical-source adapter
specification, and the operator/exporter authority/output policy. Then authorize
that exact contract hash and source evidence set. This must not release CSI500
samples, labels or granular diagnostics or loosen sealed permissions. None of
these real-use approval/deployment steps occurs automatically in NEXT-02.
