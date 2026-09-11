# Quant Stack V1 Release Audit

Status: `RC_01_LOCAL_ACCEPTANCE_PASS_CI_PENDING`

Release candidate commit: `34ee71d`

## Engineering acceptance

- Python 3.11.15 with dependencies pinned by `uv.lock`.
- `ruff check`, `ruff format --check` and strict `mypy src`: PASS.
- Full offline pytest with coverage: 166 passed in 78.43 seconds.
- Combined statement/branch coverage: 73%.
- User systemd service, timer and failure unit: `systemd-analyze verify` PASS.
- The host check emitted an unrelated warning about
  `/etc/systemd/system/runsunloginclient.service`; no project unit warning remained.

## RC-01 consistency evidence

- Ordinary sessions do not create monthly strategy or benchmark orders. The
  verified next common session must cross into a new calendar month.
- Existing eligible T+1 orders are still processed every session.
- Record-date dividend entitlement uses holdings after that day's paper fills.
- Accrued dividends enter NAV at entitlement and move to cash on the first
  processed date at or after the official payment date.
- Strategy, benchmark, monthly orders and HTML report must all complete before
  the account-level day-complete receipt is published. Catch-up advances only
  through those receipts.
- Every catch-up snapshot records its actual UTC generation time and an explicit
  historical-backfill flag; it is not represented as contemporaneously generated.
- systemd preview and installation do not enable or start the timer. Enabling is
  a separate command that requires `ALLOW_NETWORK=1` in the installed environment.

## Deployment and CI state

- Paper timer installed: no.
- Paper timer enabled: no.
- Automatic network task active: no.
- GitHub CI workflow now runs for pull requests plus pushes to `main`, `codex/**`
  and `issue/**`.
- Remote CI result for this release candidate: pending push.
- Merge to default branch: not performed.
- V1 tag: not created.

## Research boundary

Issue 009 remains `PASS_CONTROLLED_RECOVERY` with the research outcome
`NO_EVIDENCE_OF_EDGE`. RC-01 changes paper operation timing and accounting only;
it does not change the frozen strategy, universe, costs, historical result or
locked-test evidence. No locked test was rerun.

The September engineering account and the formal 2026-10 through 2028-03
prospective account must use distinct account IDs, databases and performance
histories. The first prospective signal remains the verified October 2026
natural month-end close.

## Remaining release steps

Push this commit to run actual GitHub CI. After CI passes, the release remains a
paper-only V1 candidate until installation is reviewed and the planned 15-day
operations observation is completed. No real-order adapter is present or allowed.
