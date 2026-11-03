"""Labeled DNS fixtures.

Each case is a synthetic domain whose misconfiguration is known by construction,
so the expected finding ids are ground truth, not a judgement call. Domains use
the reserved .test TLD and never touch real DNS.

Honest scope: because the cases are synthetic, scoring 100% here shows the
checks implement the rules correctly and will catch regressions. It does NOT
show how often real-world domains are misdiagnosed.
"""
from __future__ import annotations

GOOD_DMARC = "v=DMARC1; p=quarantine; rua=mailto:dmarc@{d}"
# 2048-bit RSA SubjectPublicKeyInfo (RFC 8301 SHOULD minimum), generated for fixtures.
DKIM_P_2048 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0WnEGDIPFNH5UG2le9lh"
    "EVoIylPAbo71yySYoMAYmZ94+vXDrZSW2aNgJtmlY5nR4UIXaMx8WpgGdlbv5aDu"
    "33StF6+Mbd4vvAWC7wFF7KDEE6TugTZNME3YNlzN01HAtZfUBeNQgqVtwAQwS1QS"
    "/ygP3zYFC3o892C8Jz1Jp+Si4cM3BeylvBm1OQZbU+SapxM15+q3XzQdiNS+6EzA"
    "WUCD7Ika9lwh8ES5Cuyk1EmFUmjbHX1fmKQ6NYGvK4M8LoIImN5X9J+EI8ZXW7Ks"
    "2eKX4OvYtuv+4xumUmn4Y4nj4e8FsrNdqW7X+ZVKhfETlNvxTBILASoyvmqScwAH"
    "MwIDAQAB"
)
# 1024-bit RSA key — still common, but below the RFC 8301 SHOULD size.
DKIM_P_1024 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCzX7QtE91+aVHFcIV82S12Thrc"
    "VxO0Dh39MurQD37tT8mY5FxEzl8zzVsfbFJsH8c6bOqrd7SIZTiPQNaO2WI/dqC6"
    "r+VULdITDNF8ZbN0lpkwYhWymc22cAAYgRwHPf7tI2yFm/RsxxhANDQsbuXgW2y9"
    "CF90eo/6kEq4C9yAFwIDAQAB"
)
GOOD_DKIM = f"v=DKIM1; k=rsa; p={DKIM_P_2048}"
WEAK_DKIM = f"v=DKIM1; k=rsa; p={DKIM_P_1024}"
GOOGLE_SPF = "v=spf1 include:_spf.google.com ~all"


def make(domain: str, *, spf="__default__", dmarc="__default__", mx="__default__",
         dkim="__default__", extra: dict | None = None) -> dict:
    """Build a clean domain, then let each case override one piece."""
    recs: dict[str, dict[str, list[str]]] = {}
    recs[domain] = {"TXT": [], "MX": []}
    spf = [GOOGLE_SPF] if spf == "__default__" else spf
    mx = ["aspmx.l.google.com"] if mx == "__default__" else mx
    recs[domain]["TXT"] = list(spf)
    recs[domain]["MX"] = list(mx)
    recs["_spf.google.com"] = {"TXT": ["v=spf1 ip4:35.190.247.0/24 ip4:64.233.160.0/19 ~all"]}
    dmarc = [GOOD_DMARC.format(d=domain)] if dmarc == "__default__" else dmarc
    if dmarc:
        recs[f"_dmarc.{domain}"] = {"TXT": list(dmarc)}
    dkim = [GOOD_DKIM] if dkim == "__default__" else dkim
    if dkim:
        recs[f"google._domainkey.{domain}"] = {"TXT": list(dkim)}
    recs.update(extra or {})
    return recs


def _chain(prefix: str, n: int) -> dict:
    """n leaf includes, each a free (ip4-only) policy: root costs exactly n lookups."""
    return {f"{prefix}{i}.test": {"TXT": ["v=spf1 ip4:192.0.2.%d -all" % i]} for i in range(1, n + 1)}


def _root_with_includes(prefix: str, n: int, tail: str = "-all") -> str:
    return "v=spf1 " + " ".join(f"include:{prefix}{i}.test" for i in range(1, n + 1)) + f" {tail}"


CASES: list[dict] = []


def case(name: str, domain: str, records: dict, expected: list[str], note: str = ""):
    CASES.append({"name": name, "domain": domain, "records": records,
                  "expected": sorted(expected), "note": note})


case("clean", "clean.test", make("clean.test"), [])

case("spf_missing", "nospf.test", make("nospf.test", spf=[]), ["SPF_MISSING"])

case("spf_multiple", "multispf.test",
     make("multispf.test", spf=[GOOGLE_SPF, "v=spf1 include:spf.protection.outlook.com ~all"]),
     ["SPF_MULTIPLE"])

case("spf_11_lookups", "eleven.test",
     make("eleven.test", spf=[_root_with_includes("i", 11)], extra=_chain("i", 11)),
     ["SPF_TOO_MANY_LOOKUPS"], "boundary: one over the limit")

case("spf_exactly_10_lookups", "ten.test",
     make("ten.test", spf=[_root_with_includes("j", 10)], extra=_chain("j", 10)),
     [], "boundary: exactly at the limit must NOT be flagged")

case("spf_nested_lookups", "nested.test",
     make("nested.test", spf=["v=spf1 include:n1.test a mx -all"], extra={
         "n1.test": {"TXT": ["v=spf1 include:n2.test include:n3.test a mx -all"]},
         "n2.test": {"TXT": ["v=spf1 include:n4.test include:n5.test a -all"]},
         "n3.test": {"TXT": ["v=spf1 a mx -all"]},
         "n4.test": {"TXT": ["v=spf1 a mx -all"]},
         "n5.test": {"TXT": ["v=spf1 a -all"]},
     }),
     ["SPF_TOO_MANY_LOOKUPS", "SPF_VOID_LOOKUPS"],
     "nested includes, hand-counted: 15 lookups; a/mx on TXT-only leaves are void (>2)")

case("spf_include_loop", "loop.test",
     make("loop.test", spf=["v=spf1 include:loopa.test -all"], extra={
         "loopa.test": {"TXT": ["v=spf1 include:loopb.test -all"]},
         "loopb.test": {"TXT": ["v=spf1 include:loopa.test -all"]},
     }),
     ["SPF_TOO_MANY_LOOKUPS"], "must terminate and report the loop, not hang")

case("spf_plus_all", "plusall.test",
     make("plusall.test", spf=["v=spf1 include:_spf.google.com +all"]), ["SPF_PLUS_ALL"])

case("spf_bare_all_is_plus", "bareall.test",
     make("bareall.test", spf=["v=spf1 include:_spf.google.com all"]), ["SPF_PLUS_ALL"],
     "an 'all' with no qualifier defaults to +")

case("spf_neutral_all", "neutral.test",
     make("neutral.test", spf=["v=spf1 include:_spf.google.com ?all"]), ["SPF_NEUTRAL_ALL"])

case("spf_no_all", "noall.test",
     make("noall.test", spf=["v=spf1 include:_spf.google.com"]), ["SPF_NO_ALL"])

case("spf_redirect_ok", "redirect.test",
     make("redirect.test", spf=["v=spf1 redirect=_spf.google.com"]), [],
     "redirect replaces the all term and must not trigger SPF_NO_ALL")

case("spf_ptr", "ptr.test",
     make("ptr.test", spf=["v=spf1 ptr include:_spf.google.com -all"]), ["SPF_PTR"])

case("dmarc_missing", "nodmarc.test", make("nodmarc.test", dmarc=[]), ["DMARC_MISSING"])

case("dmarc_none_with_rua", "dmarcnone.test",
     make("dmarcnone.test", dmarc=["v=DMARC1; p=none; rua=mailto:r@dmarcnone.test"]),
     ["DMARC_POLICY_NONE"])

case("dmarc_none_no_rua", "dmarcbare.test",
     make("dmarcbare.test", dmarc=["v=DMARC1; p=none"]),
     ["DMARC_POLICY_NONE", "DMARC_NO_REPORTING"])

case("dmarc_invalid", "dmarcbad.test",
     make("dmarcbad.test", dmarc=["v=DMARC1; rua=mailto:r@dmarcbad.test"]), ["DMARC_INVALID"])

case("dmarc_multiple", "dmarcdup.test",
     make("dmarcdup.test", dmarc=["v=DMARC1; p=none", "v=DMARC1; p=reject"]), ["DMARC_MULTIPLE"])

case("dmarc_partial_pct", "dmarcpct.test",
     make("dmarcpct.test", dmarc=["v=DMARC1; p=quarantine; pct=50; rua=mailto:r@dmarcpct.test"]),
     ["DMARC_PCT_PARTIAL"])

case("mx_missing", "nomx.test", make("nomx.test", mx=[]), ["MX_MISSING"])

case("dkim_missing", "nodkim.test", make("nodkim.test", dkim=[]), ["DKIM_NOT_FOUND"])

case("dkim_weak_1024", "weakdkim.test", make("weakdkim.test", dkim=[WEAK_DKIM]),
     ["DKIM_WEAK_KEY"], "RFC 8301 SHOULD >=2048; 1024-bit must be flagged")

case("dkim_strong_2048", "strongdkim.test", make("strongdkim.test", dkim=[GOOD_DKIM]),
     [], "boundary: exactly 2048-bit RSA must NOT be flagged")

case("dkim_microsoft_selector_ok", "m365.test",
     make("m365.test", spf=["v=spf1 include:spf.protection.outlook.com ~all"], dkim=[],
          extra={"spf.protection.outlook.com": {"TXT": ["v=spf1 ip4:40.92.0.0/15 -all"]},
                 "selector1._domainkey.m365.test": {"TXT": [GOOD_DKIM]}}),
     [], "selector1 is a Microsoft 365 default and must be found")

case("spf_void_3_includes", "void3.test",
     make("void3.test",
          spf=["v=spf1 include:missing1.test include:missing2.test include:missing3.test -all"]),
     ["SPF_VOID_LOOKUPS"], "three includes to empty names exceed the RFC 7208 void limit of 2")

case("spf_void_exactly_2", "void2.test",
     make("void2.test",
          spf=["v=spf1 include:missing1.test include:missing2.test -all"]),
     [], "boundary: exactly two void lookups must NOT be flagged")

case("dmarc_sp_none_under_reject", "dmarcsp.test",
     make("dmarcsp.test",
          dmarc=["v=DMARC1; p=reject; sp=none; rua=mailto:r@dmarcsp.test"]),
     ["DMARC_SP_NONE"], "sp=none under p=reject leaves subdomains unenforced")

case("dmarc_sp_inherits_ok", "dmarcspinherit.test",
     make("dmarcspinherit.test",
          dmarc=["v=DMARC1; p=reject; rua=mailto:r@dmarcspinherit.test"]),
     [], "absent sp= inherits p= and must NOT be flagged")

case("dmarc_strict_alignment", "dmarcstrict.test",
     make("dmarcstrict.test",
          dmarc=["v=DMARC1; p=quarantine; adkim=s; aspf=s; rua=mailto:r@dmarcstrict.test"]),
     ["DMARC_STRICT_ALIGNMENT"], "strict adkim/aspf changes advice for subdomain sending")

case("nxdomain_everything_missing", "ghost.test", {},
     ["DKIM_NOT_FOUND", "DMARC_MISSING", "MX_MISSING", "SPF_MISSING"],
     "a domain with no records at all")

case("worst_case_combo", "mess.test",
     make("mess.test", spf=["v=spf1 ptr include:_spf.google.com +all"],
          dmarc=["v=DMARC1; p=none"], mx=[], dkim=[]),
     ["DKIM_NOT_FOUND", "DMARC_NO_REPORTING", "DMARC_POLICY_NONE", "MX_MISSING",
      "SPF_PLUS_ALL", "SPF_PTR"], "several independent problems at once")


# Advisory pack fixtures (run with ALL_DNS_PACKS). Separate from CASES so core
# detection metrics stay comparable.
ADVISORY_CASES: list[dict] = []


def advisory_case(name: str, domain: str, records: dict, expected: list[str], note: str = ""):
    ADVISORY_CASES.append({
        "name": name, "domain": domain, "records": records,
        "expected": sorted(expected), "note": note,
    })


_ADVISORY_BASE = ["BIMI_MISSING", "MTA_STS_MISSING", "TLS_RPT_MISSING"]

advisory_case(
    "advisory_all_missing_on_clean",
    "clean.test",
    make("clean.test"),
    _ADVISORY_BASE,
    "core clean domain still lacks optional BIMI/MTA-STS/TLS-RPT",
)

advisory_case(
    "advisory_bimi_present",
    "bimiok.test",
    make(
        "bimiok.test",
        extra={"default._bimi.bimiok.test": {"TXT": ["v=BIMI1; l=https://example.com/logo.svg"]}},
    ),
    ["MTA_STS_MISSING", "TLS_RPT_MISSING"],
    "boundary: BIMI present must not flag BIMI_MISSING",
)

advisory_case(
    "advisory_mta_sts_present",
    "stsok.test",
    make(
        "stsok.test",
        extra={"_mta-sts.stsok.test": {"TXT": ["v=STSv1; id=20240101T000000Z"]}},
    ),
    ["BIMI_MISSING", "TLS_RPT_MISSING"],
    "boundary: MTA-STS TXT present must not flag MTA_STS_MISSING",
)

advisory_case(
    "advisory_tls_rpt_present",
    "tlsok.test",
    make(
        "tlsok.test",
        extra={"_smtp._tls.tlsok.test": {"TXT": ["v=TLSRPTv1; rua=mailto:tls@tlsok.test"]}},
    ),
    ["BIMI_MISSING", "MTA_STS_MISSING"],
    "boundary: TLS-RPT present must not flag TLS_RPT_MISSING",
)
