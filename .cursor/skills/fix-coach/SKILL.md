---
name: fix-coach
description: >-
  Build a paste-ready registrar DNS fix packet from Setup Doctor findings. Use
  when the user asks how to fix SPF, DKIM, DMARC, or MX, asks for records to
  paste, or names Cloudflare, Namecheap, GoDaddy, or Google Domains. Does not
  invent record strings.
---

# Fix Coach

Paste-ready registrar steps for one domain. Record strings come only from the engine fix packet.

## Provider

If the user has not named a registrar, ask which of these `--fix-packet` choices to use:

- `cloudflare`
- `namecheap`
- `godaddy`
- `google_domains`

Do not guess a provider.

## Run

Need a domain and a provider. From the repo root (or with `setup-doctor` on PATH):

```bash
python -m setup_doctor DOMAIN --json --fix-packet PROVIDER
```

There is no separate MCP fix-packet tool. Use this CLI flag.

## Present

Show the `fix_packet` content (its markdown or the `steps` / `notes` fields). Keep every `finding_id` the packet names. Do not add TXT, CNAME, MX, SPF, DKIM, or DMARC strings that are not in the packet. Do not reorder steps.

If the command fails with exit code 2, `resolver_error`, or `NXDOMAIN`, stop. That is an outage or a missing domain, not a list of records to publish.

## Hand off

After they change DNS, re-run Domain Doctor once records can propagate. If they asked whether Instantly may activate, that answer is Launch Gate, after the recheck.
