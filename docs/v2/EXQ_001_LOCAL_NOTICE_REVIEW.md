# EXQ-001 local notice review, 2026-09-19

Status: PARTIAL_TEXT_EXTRACTION; candidate qualification remains BLOCKED_DATA.

The user-returned CNINFO discovery receipt c619ec2af0086d5c9bb83a4d595e5668e981dbfcb4f3509882c3eaad095dacd4 lists 62 candidate PDFs. A local search restricted to the existing CNINFO public-discovery and SZSE consolidated-evidence archives located 54 matching PDF bodies. All 54 actual byte hashes matched the receipt. Extraction produced 223 complete, page-numbered candidate sentences. Eight PDFs had no copy in those two local archives; this does not mean that the sealed capture lacks them.

Local review inventory: /tmp/exq-local-review/e209a5c1991b82375263ed9cb3e5e66f318cba9b950492df1fc1583bbf7a4a3c.json. This temporary review artifact includes local source paths, PDF identities and text hashes. It is not a replacement for the original sealed receipt, and is not a qualification artifact.

## Findings affecting interpretation

- The discovery adapter requests page 1 only. Zero keyword candidates therefore do not establish an exhaustive negative search. Missing pagination remains an engineering limitation.
- ZTE notice 223ef35856061257ae14bb42e270a1ee62efe969a441d7a3c7fe980e5162f8b9 explicitly says that shares *will* resume on 2016-04-07. It cannot establish completed resumption under the existing actual-resumption validator.
- The Sanju discovery task includes bond suspension/resumption notices. Their title matches do not establish stock trading status.
- The existing actual-resumption validator does not validate corporate-action cash amounts, record dates, payment dates or share conversion accounting. No corporate-action qualification follows from extracting suspension sentences.
- The old extractor trusted the hash in a filename without checking bytes and could truncate sentence prefixes. It now recomputes the actual PDF hash before extraction and retains full sentences, preserving planned or negated language.

No newly explained session count is claimed. The 223 sentences require reviewed claims, catalog-to-issuer binding, date and continuity checks before classification. Previously reported residual counts and immutable evidence are unchanged. FORMAL_PIT_STATUS and FORMAL_RESEARCH_STATUS remain BLOCKED_DATA; CSI500 remains NOT_STARTED.
