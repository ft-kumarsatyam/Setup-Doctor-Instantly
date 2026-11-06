# Public DNS corpus

Frozen SPF, DKIM, DMARC, and MX records for 40 public domains, snapshotted on 2026-11-05 via DNS-over-HTTPS (Cloudflare, Google fallback). The SPF include/redirect closure is included so offline checks see the same tree.

- `public_dns.json` — records
- `labels.json` — expected finding ids, written from the records (not copied out of a live model)
- `rewrite_pairs.jsonl` — grounded `{id, explanation}` plans for domains that have findings. This is the rewrite training/eval set. It does not add, drop, or re-rank findings.

`python evals/run_evals.py` scores this corpus on its own. Those numbers are not added to the synthetic precision/recall in section 1.

The rewrite index (`src/setup_doctor/explain/rag_index.py`) is example retrieval for the LLM rewrite, built from these pairs plus the synthetic fixtures. It does not find problems, and it does not raise the synthetic or public detection score. Rebuild with `python evals/corpus/build_rag_index.py` after a fixture or pair change.

Zone-scale dumps (OpenINTEL, the 2023 DMARC study of com/net/org) are not vendored. Refresh the snapshot with `python evals/corpus/fetch_public_dns.py` (network), then review `labels.json` before changing expected ids. CI does not query DNS.

`DKIM_NOT_FOUND` here means none of the nine default selectors had a usable key. A provider can still sign with a selector this list does not guess.
