"""Deterministic DNS checks. This module is the source of truth.

Each check returns Findings with concrete evidence. Nothing here calls an LLM.
Severity reflects impact on cold-email deliverability under the Google, Yahoo
and Microsoft bulk-sender rules (authenticate with SPF/DKIM/DMARC, keep
complaints low).
"""
from __future__ import annotations

from . import spf
from .models import Finding, prioritize
from .resolver import Resolver

DEFAULT_DKIM_SELECTORS = (
    "google", "selector1", "selector2", "default", "k1", "s1", "s2", "mail", "dkim",
)

SPF_G = "`v=spf1 include:_spf.google.com ~all`"
SPF_M = "`v=spf1 include:spf.protection.outlook.com ~all`"


def check_spf(domain: str, resolver: Resolver) -> list[Finding]:
    records = spf.find_spf_records(resolver.txt(domain))
    if not records:
        return [Finding(
            "SPF_MISSING", "high",
            f"No SPF record found at {domain}",
            "Without SPF, receivers cannot verify your mail server is allowed to send for this domain, "
            "and bulk-sender rules require it to pass.",
            f"Publish exactly one TXT record at {domain}. Google Workspace: {SPF_G}. Microsoft 365: {SPF_M}.",
        )]
    if len(records) > 1:
        return [Finding(
            "SPF_MULTIPLE", "high",
            f"{len(records)} SPF records found at {domain} (must be exactly one)",
            "Two or more SPF records is a permanent error under RFC 7208, so SPF fails for every message.",
            "Merge all mechanisms into a single `v=spf1 ...` record and delete the others.",
            {"record_count": str(len(records))},
        )]

    record = records[0]
    out: list[Finding] = []

    lookups, loop = spf.count_lookups(domain, resolver)
    if lookups > 10 or loop:
        detail = f"needs {lookups} DNS lookups (limit is 10)" if lookups > 10 else "contains an include loop"
        out.append(Finding(
            "SPF_TOO_MANY_LOOKUPS", "high",
            f"SPF record {detail}",
            "Receivers stop after 10 lookups and return a permanent error, so SPF fails even though the record looks valid.",
            "Remove unused include: entries, replace include: chains with ip4:/ip6: ranges (SPF flattening), "
            "and use dedicated sending domains with a minimal SPF record.",
            {"lookups": str(lookups), "loop": str(loop).lower(), "record": record},
        ))

    q = spf.all_qualifier(record)
    if q == "+":
        out.append(Finding(
            "SPF_PLUS_ALL", "critical",
            "SPF ends with +all, which authorizes every server on the internet",
            "Anyone can spoof this domain and still pass SPF, which destroys domain reputation and trust.",
            "Change the ending to `~all` (soft fail) or `-all` (hard fail).",
            {"record": record},
        ))
    elif q == "?":
        out.append(Finding(
            "SPF_NEUTRAL_ALL", "medium",
            "SPF ends with ?all (neutral), so it gives receivers no policy signal",
            "A neutral result carries no authentication weight.",
            "Change the ending to `~all` or `-all`.",
            {"record": record},
        ))
    elif q is None and not spf.has_redirect(record):
        out.append(Finding(
            "SPF_NO_ALL", "medium",
            "SPF has no terminating all mechanism",
            "Without a terminating mechanism the default result is neutral, so unlisted senders are not rejected.",
            "Append `~all` or `-all` to the record.",
            {"record": record},
        ))

    if spf.uses_ptr(record):
        out.append(Finding(
            "SPF_PTR", "low",
            "SPF uses the deprecated ptr mechanism",
            "RFC 7208 discourages ptr: it is slow, unreliable, and costs a lookup.",
            "Replace ptr with explicit ip4:/ip6: or include: entries.",
            {"record": record},
        ))
    return out


def check_dkim(domain: str, resolver: Resolver, selectors: tuple[str, ...]) -> list[Finding]:
    for sel in selectors:
        for txt in resolver.txt(f"{sel}._domainkey.{domain}"):
            low = txt.lower()
            if "v=dkim1" in low or "p=" in low:
                return []
    return [Finding(
        "DKIM_NOT_FOUND", "medium",
        f"No DKIM key found at {len(selectors)} common selectors for {domain}",
        "DKIM lets receivers verify the message was not altered and ties it to your domain. Bulk-sender rules require it.",
        "Generate a DKIM key in your mailbox provider (Google Admin or Microsoft 365), publish it, and confirm it validates. "
        "If you already did, re-run with --dkim-selector set to your selector name.",
        {"selectors_tried": ",".join(selectors),
         "limitation": "DKIM selectors cannot be enumerated from DNS, so a custom selector can cause a false positive"},
    )]


def _parse_dmarc(record: str) -> dict[str, str]:
    tags = {}
    for part in record.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k.strip().lower()] = v.strip()
    return tags


def check_dmarc(domain: str, resolver: Resolver) -> list[Finding]:
    name = f"_dmarc.{domain}"
    records = [t.strip() for t in resolver.txt(name) if t.strip().lower().startswith("v=dmarc1")]
    if not records:
        return [Finding(
            "DMARC_MISSING", "high",
            f"No DMARC record found at {name}",
            "Google, Yahoo and Microsoft require a DMARC record for bulk senders; without one mail is increasingly rejected.",
            f"Publish a TXT record at {name}: `v=DMARC1; p=none; rua=mailto:dmarc@{domain}`. Tighten to quarantine later.",
        )]
    if len(records) > 1:
        return [Finding(
            "DMARC_MULTIPLE", "medium",
            f"{len(records)} DMARC records found at {name} (must be exactly one)",
            "Receivers ignore DMARC entirely when more than one record is present.",
            "Delete the extra records so exactly one `v=DMARC1` record remains.",
            {"record_count": str(len(records))},
        )]

    record = records[0]
    tags = _parse_dmarc(record)
    if "p" not in tags:
        return [Finding(
            "DMARC_INVALID", "medium",
            "DMARC record has no p= policy tag",
            "A record without a policy is invalid and receivers will not apply DMARC.",
            "Add a policy, for example `v=DMARC1; p=none; rua=mailto:dmarc@" + domain + "`.",
            {"record": record},
        )]

    out: list[Finding] = []
    policy = tags["p"].lower()
    if policy == "none":
        out.append(Finding(
            "DMARC_POLICY_NONE", "low",
            "DMARC policy is p=none (monitoring only)",
            "p=none meets the minimum for bulk senders but does not protect the domain from spoofing.",
            "After reviewing reports for a few weeks, move to `p=quarantine`, then `p=reject`.",
            {"record": record},
        ))
    else:
        try:
            pct = int(tags.get("pct", "100"))
        except ValueError:
            pct = 100
        if pct < 100:
            out.append(Finding(
                "DMARC_PCT_PARTIAL", "low",
                f"DMARC applies to only {pct}% of mail (pct={pct})",
                "A partial rollout leaves the remaining mail unprotected.",
                "Raise pct to 100 once reports look clean.",
                {"record": record, "pct": str(pct)},
            ))
    if "rua" not in tags:
        out.append(Finding(
            "DMARC_NO_REPORTING", "info",
            "DMARC has no rua= reporting address",
            "Without aggregate reports you cannot see who is sending as your domain or what is failing.",
            f"Add `rua=mailto:dmarc@{domain}` to the record.",
            {"record": record},
        ))
    return out


def check_mx(domain: str, resolver: Resolver) -> list[Finding]:
    if resolver.mx(domain):
        return []
    return [Finding(
        "MX_MISSING", "medium",
        f"No MX record found for {domain}",
        "Replies must reach a real mailbox, and many receivers distrust sending domains that cannot receive mail.",
        "Add the MX records your mailbox provider gives you.",
    )]


def run_checks(domain: str, resolver: Resolver,
               dkim_selectors: tuple[str, ...] = DEFAULT_DKIM_SELECTORS) -> list[Finding]:
    domain = domain.strip().lower().rstrip(".")
    findings = (
        check_spf(domain, resolver)
        + check_dkim(domain, resolver, dkim_selectors)
        + check_dmarc(domain, resolver)
        + check_mx(domain, resolver)
    )
    return prioritize(findings)
