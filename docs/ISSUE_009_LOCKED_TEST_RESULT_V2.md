# Issue 009 Locked-Test Result V2

Status: `INVALID_RESEARCH_RESULT`
Issue 009: `BLOCKED_CONTAMINATED`

## Frozen attempt

- Precommit ID: `d1c3c371864885134f4a733cebdc09b0fedcd2ca69ad7a8a9c1898c4374fe7c6`
- Code commit: `10275b30e82f9d3b394e4ffc2de1c5138dc31965`
- Precommit commit: `a9b96c01ddf713e2860c175f674aae2bf2f93453`
- Data snapshot ID: `6f33e58c7681a3444d05933d7605672a22940ca5a5039b748d962c419fea4750`
- Locked interval: 2024-01-02 through 2026-09-09.

The runner atomically consumed this precommit before reading locked data. The
attempt receipt SHA-256 is
`ee0a73f596b7dfc79892c919526f1fa5845c3e40325726d6804c35dc4af1195e`.

## Failure

The process read and calculated the frozen runs, then failed while serializing
the first experiment-registry payload. `WalkForwardSplit` contains `date`
objects, while the registry serializer did not define their canonical encoding.
Python raised `TypeError: Object of type date is not JSON serializable` before
any formal metrics or registry record was persisted.

The immutable failure receipt SHA-256 is
`f363c065c07ed96e44b5136326c9b6773d6e5114d2ca5c4092af1ba3734a7820`.

The serializer now has a deterministic date regression test, but the same
precommit and locked interval must not be executed again. The failed process
already accessed the holdout, and V2 explicitly makes every attempt fail-closed.
No `ROBUST_OUTPERFORMANCE_OBSERVED` or `NO_EVIDENCE_OF_EDGE` conclusion can be
reported because no valid formal result was retained.

## Acceptance

Issue 009 does not pass. D0 remains valid, but the locked-test evidence is
contaminated by an execution failure. A future protocol may create a new locked
test only from genuinely unused observations collected after 2026-09-09; the
current interval remains permanently consumed. Issue 010-012 remain forbidden.
