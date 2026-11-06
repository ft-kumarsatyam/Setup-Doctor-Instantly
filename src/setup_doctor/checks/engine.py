"""Deterministic DNS checks. This module is the source of truth.

Each check returns Findings with concrete evidence. Nothing here calls an LLM.
Severity reflects impact on cold-email deliverability under the Google, Yahoo
and Microsoft bulk-sender rules (authenticate with SPF/DKIM/DMARC, keep
complaints low).
"""
from __future__ import annotations

import base64
import binascii
import re

from setup_doctor.core.models import Finding
from setup_doctor.dns import spf
from setup_doctor.dns.resolver import Resolver

DEFAULT_DKIM_SELECTORS = (
    "google", "selector1", "selector2", "default", "k1", "s1", "s2", "mail", "dkim",
)

SPF_G = "`v=spf1 include:_spf.google.com ~all`"
SPF_M = "`v=spf1 include:spf.protection.outlook.com ~all`"

_DKIM_TAG_RE = re.compile(r"([a-z]+)=([^;]*)", re.I)


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

    # RFC 7208 §4.6.4: more than two void lookups SHOULD cause PermError.
    voids = spf.count_void_lookups(domain, resolver)
    if voids > 2:
        out.append(Finding(
            "SPF_VOID_LOOKUPS", "medium",
            f"SPF causes {voids} void DNS lookups (limit is 2)",
            "RFC 7208 section 4.6.4: DNS lookups that return nothing (NXDOMAIN/NODATA) for "
            "include/a/mx/exists/redirect count as void lookups; more than two is a permanent error, "
            "so SPF fails for every message.",
            "Remove or fix include:/a/mx/exists/redirect= targets that do not resolve, then re-check.",
            {"void_lookups": str(voids), "record": record},
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


def _parse_dkim_tags(record: str) -> dict[str, str]:
    return {k.lower(): v.strip() for k, v in _DKIM_TAG_RE.findall(record)}


def _der_len(data: bytes, i: int) -> tuple[int, int]:
    length = data[i]
    i += 1
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[i:i + n], "big")
        i += n
    return length, i


def dkim_rsa_key_bits(p_b64: str) -> int | None:
    """Return RSA modulus bit length from a DKIM p= value, or None if unknown.

    DKIM RSA keys (RFC 6376 / RFC 8301) publish the public key as base64 DER
    SubjectPublicKeyInfo. We only report a size when that structure parses.
    """
    cleaned = "".join(p_b64.split())
    if not cleaned or cleaned == "":
        return None
    try:
        raw = base64.b64decode(cleaned, validate=False)
    except (binascii.Error, ValueError):
        return None
    try:
        if not raw or raw[0] != 0x30:
            return None
        _, i = _der_len(raw, 1)
        if i >= len(raw) or raw[i] != 0x30:  # AlgorithmIdentifier
            return None
        alen, j = _der_len(raw, i + 1)
        i = j + alen
        if i >= len(raw) or raw[i] != 0x03:  # subjectPublicKey BIT STRING
            return None
        _, i = _der_len(raw, i + 1)
        if i >= len(raw) or raw[i] != 0x00:
            return None
        i += 1
        if i >= len(raw) or raw[i] != 0x30:  # RSAPublicKey
            return None
        _, i = _der_len(raw, i + 1)
        if i >= len(raw) or raw[i] != 0x02:  # modulus INTEGER
            return None
        mlen, i = _der_len(raw, i + 1)
        modulus = raw[i:i + mlen]
        if not modulus:
            return None
        if modulus[0] == 0:
            modulus = modulus[1:]
        return len(modulus) * 8
    except (IndexError, ValueError):
        return None


def check_dkim(domain: str, resolver: Resolver, selectors: tuple[str, ...]) -> list[Finding]:
    for sel in selectors:
        for txt in resolver.txt(f"{sel}._domainkey.{domain}"):
            low = txt.lower()
            if "v=dkim1" not in low and "p=" not in low:
                continue
            tags = _parse_dkim_tags(txt)
            # RFC 8301 §3.2: Signers SHOULD use RSA keys of at least 2048 bits.
            k = tags.get("k", "rsa").lower()
            if k == "rsa" and "p" in tags:
                # RFC 6376: an empty p= revokes the key. It is not a usable key,
                # so keep looking at the remaining selectors.
                if tags["p"].strip() == "":
                    continue
                bits = dkim_rsa_key_bits(tags["p"])
                if bits is not None and bits < 2048:
                    return [Finding(
                        "DKIM_WEAK_KEY", "medium",
                        f"DKIM RSA key at selector '{sel}' is {bits} bits (below 2048)",
                        "RFC 8301 recommends RSA keys of at least 2048 bits; shorter keys are easier to "
                        "attack offline and some receivers weigh key length when judging signatures.",
                        "Generate a new 2048-bit (or larger) DKIM key in your mailbox provider, publish "
                        f"the new TXT at {sel}._domainkey.{domain}, and switch signing to it.",
                        {"selector": sel, "bits": str(bits), "record": txt},
                    )]
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
        # RFC 7489 §6.3: sp= is the subdomain policy; absent means inherit p=.
        # Flag only when sp=none under a stronger organizational policy — that
        # leaves mail.example.com unprotected while example.com is locked down.
        sp = tags.get("sp", "").lower()
        if sp == "none" and policy in ("quarantine", "reject"):
            out.append(Finding(
                "DMARC_SP_NONE", "medium",
                f"DMARC subdomain policy is sp=none while p={policy}",
                "Subdomains inherit no enforcement, so spoofed mail from host.yourdomain.com can still land "
                "while the apex policy looks strict.",
                f"Set `sp={policy}` (or omit sp so it inherits p=), unless you intentionally monitor subdomains only.",
                {"record": record, "p": policy, "sp": sp},
            ))

    # RFC 7489 §6.3: adkim/aspf default to relaxed (r). Strict (s) fails when the
    # From domain is a subdomain of the aligned SPF/DKIM domain — common for cold email.
    strict_bits = []
    if tags.get("adkim", "r").lower() == "s":
        strict_bits.append("adkim=s")
    if tags.get("aspf", "r").lower() == "s":
        strict_bits.append("aspf=s")
    if strict_bits:
        joined = " and ".join(strict_bits)
        out.append(Finding(
            "DMARC_STRICT_ALIGNMENT", "low",
            f"DMARC uses strict alignment ({joined})",
            "Strict alignment requires an exact organizational-domain match; sending from a subdomain "
            "(e.g. news.example.com) while SPF/DKIM cover example.com will fail DMARC.",
            "Switch to relaxed alignment (`adkim=r; aspf=r`, the defaults) unless every From domain "
            "exactly matches your SPF and DKIM domains.",
            {"record": record, "tags": joined},
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
    # RFC 7505 null MX is a single dot. After the trailing dot is stripped the
    # exchange is empty, and that name does not accept mail.
    if any(h.strip().rstrip(".") for h in resolver.mx(domain)):
        return []
    return [Finding(
        "MX_MISSING", "medium",
        f"No MX record found for {domain}",
        "Replies must reach a real mailbox, and many receivers distrust sending domains that cannot receive mail.",
        "Add the MX records your mailbox provider gives you.",
    )]


def check_bimi(domain: str, resolver: Resolver) -> list[Finding]:
    """Advisory BIMI presence. Absence is info — BIMI is optional for cold email."""
    name = f"default._bimi.{domain}"
    records = [t for t in resolver.txt(name) if "v=bimi1" in t.lower()]
    if records:
        return []
    return [Finding(
        "BIMI_MISSING", "info",
        f"No BIMI record at {name}",
        "BIMI can show a brand logo in supporting inboxes when DMARC is enforced; it is optional for deliverability.",
        f"After DMARC is at p=quarantine or p=reject with a VMC, publish TXT at {name}: "
        "`v=BIMI1; l=https://example.com/logo.svg`.",
    )]


def check_mta_sts(domain: str, resolver: Resolver) -> list[Finding]:
    """Advisory MTA-STS DNS TXT. Policy file fetch is out of scope (no HTTP in checks)."""
    name = f"_mta-sts.{domain}"
    records = [t for t in resolver.txt(name) if "v=stsv1" in t.lower()]
    if records:
        return []
    return [Finding(
        "MTA_STS_MISSING", "info",
        f"No MTA-STS TXT record at {name}",
        "MTA-STS tells receiving MTAs to require TLS for your domain; useful for inbound security, optional for cold-email send setup.",
        f"Publish TXT at {name}: `v=STSv1; id=20240101T000000Z`, host a policy at "
        f"https://mta-sts.{domain}/.well-known/mta-sts.txt, then add TLS-RPT.",
    )]


def check_tls_rpt(domain: str, resolver: Resolver) -> list[Finding]:
    """Advisory TLS-RPT. Complements MTA-STS; absence is info."""
    name = f"_smtp._tls.{domain}"
    records = [t for t in resolver.txt(name) if "v=tlsrptv1" in t.lower()]
    if records:
        return []
    return [Finding(
        "TLS_RPT_MISSING", "info",
        f"No TLS-RPT record at {name}",
        "TLS reporting helps you see TLS failures for mail to your domain; optional for outbound cold-email auth.",
        f"Publish TXT at {name}: `v=TLSRPTv1; rua=mailto:tlsrpt@{domain}`.",
    )]


def run_checks(
    domain: str,
    resolver: Resolver,
    dkim_selectors: tuple[str, ...] = DEFAULT_DKIM_SELECTORS,
    *,
    packs: frozenset[str] | None = None,
) -> list[Finding]:
    """Run registered deterministic checks. Findings come only from this path.

    Default packs are core dns_auth only. Pass registry.ALL_DNS_PACKS (or include
    dns_auth_advisory) for BIMI / MTA-STS / TLS-RPT advisory findings.
    """
    from setup_doctor.checks.registry import DEFAULT_PACKS, get_default_registry

    return get_default_registry().run(
        domain,
        resolver,
        dkim_selectors=dkim_selectors,
        packs=DEFAULT_PACKS if packs is None else packs,
    )
