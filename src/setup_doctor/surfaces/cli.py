"""Command line entry point.

    python -m setup_doctor example.com
    python -m setup_doctor example.com --llm
    python -m setup_doctor broken.test --records examples/broken.json
    python -m setup_doctor --instantly-compare
    python -m setup_doctor --bulk domains.csv
"""
from __future__ import annotations

import argparse
import json
import sys

from setup_doctor.checks import (
    ALL_DNS_PACKS,
    DEFAULT_DKIM_SELECTORS,
    DEFAULT_PACKS,
    ESP_SELECTOR_PACKS,
    resolve_selectors,
)
from setup_doctor.core.result import DiagnosisSignals
from setup_doctor.dns.resolver import FixtureResolver, LiveResolver, ResolverError
from setup_doctor.explain import LLMExplainer, TemplateExplainer, anthropic_completer
from setup_doctor.integrations.instantly import (
    InstantlyClient,
    InstantlyError,
    compare_warmup_to_placement,
    render_comparison_markdown,
)
from setup_doctor.integrations.reputation import check_reputation
from setup_doctor.pipeline import diagnose_result
from setup_doctor.surfaces.bulk import parse_domain_list, run_bulk


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="setup-doctor", description="Diagnose cold-email DNS setup.")
    p.add_argument("domain", nargs="?", help="domain to diagnose (omit with --instantly-compare/--bulk)")
    p.add_argument("--records", help="JSON file of frozen DNS records (offline mode)")
    p.add_argument("--dkim-selector", action="append", help="extra DKIM selector to try (repeatable)")
    p.add_argument(
        "--esp-pack",
        action="append",
        choices=sorted(ESP_SELECTOR_PACKS),
        help="prepend ESP DKIM selector pack (repeatable)",
    )
    p.add_argument("--llm", action="store_true", help="use the Anthropic SDK for the explanation")
    p.add_argument("--json", action="store_true", help="print DiagnosisResult JSON (or Instantly/bulk JSON)")
    p.add_argument(
        "--advisory",
        action="store_true",
        help="include BIMI / MTA-STS / TLS-RPT advisory findings",
    )
    p.add_argument(
        "--reputation",
        action="store_true",
        help="attach reputation signals (unknown unless a provider is configured)",
    )
    p.add_argument(
        "--with-instantly",
        action="store_true",
        help="attach Instantly warmup/placement signals to the diagnosis (needs INSTANTLY_API_KEY)",
    )
    p.add_argument(
        "--instantly-compare",
        action="store_true",
        help="compare Instantly warmup scores to inbox-placement tests (read-only API v2)",
    )
    p.add_argument(
        "--bulk",
        metavar="FILE",
        help="diagnose many domains from a CSV or newline list",
    )
    args = p.parse_args(argv)

    if args.instantly_compare:
        return _instantly_compare(as_json=args.json)

    if args.bulk:
        return _bulk(args)

    if not args.domain:
        p.error("domain is required unless --instantly-compare or --bulk is set")

    if args.records:
        with open(args.records) as fh:
            resolver = FixtureResolver(json.load(fh))
    else:
        resolver = LiveResolver()

    explainer = LLMExplainer(anthropic_completer()) if args.llm else TemplateExplainer()
    try:
        selectors = resolve_selectors(
            explicit=tuple(args.dkim_selector or ()),
            packs=tuple(args.esp_pack or ()),
            defaults=DEFAULT_DKIM_SELECTORS,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    packs = ALL_DNS_PACKS if args.advisory else DEFAULT_PACKS
    signals = _build_signals(args)

    try:
        if isinstance(resolver, LiveResolver) and not resolver.domain_exists(args.domain):
            print(
                f"{args.domain} does not exist in DNS (NXDOMAIN), so there is nothing to diagnose.\n"
                "Check the spelling and that the domain is registered. If you are sure it exists, "
                "your resolver may be filtering it; try again from another network.",
                file=sys.stderr,
            )
            return 2
        result = diagnose_result(
            args.domain, resolver, explainer, selectors, packs=packs, signals=signals,
        )
    except ResolverError as exc:
        print(
            f"Could not complete the DNS checks: {exc}\n"
            "No diagnosis was produced (an outage is not the same as missing records).",
            file=sys.stderr,
        )
        return 2
    except InstantlyError as exc:
        print(
            f"Instantly API request failed (HTTP {exc.status}). "
            "Diagnosis was not combined with Instantly signals.",
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.report)
        if result.signals and result.signals.instantly:
            print()
            print(render_comparison_markdown(_dicts_as_comparisons(result.signals.instantly)))
    return 0


def _dicts_as_comparisons(rows: list[dict]):
    from setup_doctor.integrations.instantly import AccountComparison

    out = []
    for r in rows:
        out.append(AccountComparison(
            email=r.get("email", ""),
            warmup_score=r.get("warmup_score"),
            health_score=r.get("health_score"),
            inbox_percent=r.get("inbox_percent"),
            spam_percent=r.get("spam_percent"),
            test_ids=list(r.get("test_ids") or []),
            verdict=r.get("verdict", "unknown"),
            note=r.get("note", ""),
        ))
    return out


def _build_signals(args) -> DiagnosisSignals | None:
    if not (args.reputation or args.with_instantly):
        return None
    not_checked: list[str] = []
    instantly = None
    reputation = None
    if args.with_instantly:
        client = InstantlyClient()
        instantly = [r.to_dict() for r in compare_warmup_to_placement(client)]
    else:
        not_checked.append("instantly")
    if args.reputation:
        reputation = check_reputation(args.domain)
    else:
        not_checked.append("reputation")
    return DiagnosisSignals(
        instantly=instantly,
        reputation=reputation,
        not_checked=not_checked,
    )


def _bulk(args) -> int:
    path = args.bulk
    with open(path) as fh:
        domains = parse_domain_list(fh.read())
    if not domains:
        print("No domains found in bulk file.", file=sys.stderr)
        return 2
    if args.records:
        with open(args.records) as fh:
            resolver = FixtureResolver(json.load(fh))
    else:
        resolver = LiveResolver()
    explainer = LLMExplainer(anthropic_completer()) if args.llm else TemplateExplainer()
    selectors = resolve_selectors(
        explicit=tuple(args.dkim_selector or ()),
        packs=tuple(args.esp_pack or ()),
        defaults=DEFAULT_DKIM_SELECTORS,
    )
    report = run_bulk(domains, resolver, explainer, dkim_selectors=selectors)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.to_markdown())
    return 0


def _instantly_compare(*, as_json: bool) -> int:
    try:
        client = InstantlyClient()
        reports = compare_warmup_to_placement(client)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except InstantlyError as exc:
        print(
            f"Instantly API request failed (HTTP {exc.status}). "
            "No comparison was produced. Check key scopes and rate limits.",
            file=sys.stderr,
        )
        return 2

    if as_json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        print(render_comparison_markdown(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
