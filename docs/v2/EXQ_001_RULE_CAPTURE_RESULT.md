# EXQ-001 official execution-rule capture

Status: OFFICIAL_SOURCE_BYTES_CAPTURED_DATE_BINDING_PENDING.

Four configured CSRC/SSE/SZSE source bodies were retrieved directly from the
official URLs and content-addressed. The result receipt is
51da89c0edb84f0d936d21e20f823d4d717960b6dbca9cbc8ad8e78f0e5e83d3.

| Source | Body SHA-256 | Receipt SHA-256 |
| --- | --- | --- |
| CSRC A-share T+1 | 9c304aeaba5658e7c3e15bade1b765256e2fef3a59cf46e59e9cc80e607545d0 | 6b16e0d91a5ffc2014d0feb3784da9ec8a683a7b25ba4e12c026796b9652691e |
| SSE price-limit reference | c0b3825981dfd339e1c4aa5d15b0b9c791dc9773dea17593d486164586ca3951 | 4cc88312e12f45b55971596e2cb66985fccda915571746923f078f33aec136d2 |
| SZSE ChiNext transition | c1ddedd1f5829690db8e7338925d3bc1b3485f937cd2e9a523b81f4188e7c31b | 4411785f7a65dd03a879dd2b4dbb28a653924b413db3eebf1bf0da0995da4452 |
| SZSE ChiNext transaction rules | 30dec85f9e01121ff71a23b5989d7d483d9ea72b980440cb731d58023d9a6398 | 7d45437bea8e0982876b872d6073253808f645cb904efc86110a2a170872fd3d |

This capture proves source identity only. Applying a price limit still requires
the historical board, risk-warning status and security-specific limit parameter
at the relevant session. It does not establish historical ST status, exchange
fee schedules, broker commission, slippage, liquidity or execution-price
availability.

Source bytes and receipts are under artifacts/v2/exq_rule_sources_20260919/.
The source contract is
configs/v2/execution/exq_001_rule_evidence_sources_v1.yaml.

Candidate qualification, FORMAL_PIT_STATUS and FORMAL_RESEARCH_STATUS remain
BLOCKED_DATA; CSI500 remains NOT_STARTED.
