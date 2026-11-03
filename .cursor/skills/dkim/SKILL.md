---
name: dkim
description: >-
  DKIM diagnosis via Setup Doctor. Use for /dkim. Always pass known selectors;
  never treat guessed-selector miss as definitive absence without stating the limit.
disable-model-invocation: true
---

# /dkim

Selectors cannot be enumerated from DNS. Ask for the provider selector when unknown.

```bash
python -m setup_doctor DOMAIN --json --dkim-selector SELECTOR
# or ESP pack:
python -m setup_doctor DOMAIN --json --esp-pack google
python -m setup_doctor DOMAIN --json --esp-pack microsoft
python -m setup_doctor DOMAIN --json --esp-pack instantly
```

Filter findings to `DKIM_*`. If `DKIM_NOT_FOUND`, quote `evidence.limitation` — custom selectors can false-positive.
