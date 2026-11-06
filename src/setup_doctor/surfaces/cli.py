"""Command line entry point.

    python -m setup_doctor example.com
    python -m setup_doctor example.com --llm
    python -m setup_doctor broken.test --records examples/broken.json
    python -m setup_doctor --instantly-compare
    python -m setup_doctor --instantly-ready
    python -m setup_doctor --bulk domains.csv
    python -m setup_doctor --from-instantly
    python -m setup_doctor --share-demo
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
from setup_doctor.explain import (
    FIX_PACKET_PROVIDERS,
    LLMExplainer,
    TemplateExplainer,
    anthropic_completer,
    build_fix_packet,
    rewrite_instantly_signals,
)
from setup_doctor.integrations.instantly import (
    InstantlyClient,
    InstantlyError,
    build_pre_launch_gate,
    compare_warmup_to_placement,
    comparisons_as_dicts,
    dicts_as_comparisons,
    render_agency_report,
    render_agency_workspaces_markdown,
    render_campaign_desk_markdown,
    render_comparison_markdown,
    render_readiness_markdown,
    render_reply_desk_markdown,
    run_all_workspaces_readiness,
    run_campaign_desk,
    run_reply_desk,
    run_workspace_readiness,
    unique_sender_domains,
)
from setup_doctor.integrations.instantly.share_demo import render_share_demo, run_share_demo
from setup_doctor.integrations.reputation import check_reputation
from setup_doctor.pipeline import diagnose_result
from setup_doctor.surfaces.bulk import parse_domain_list, run_bulk


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="setup-doctor", description="Diagnose cold-email DNS setup.")
    p.add_argument(
        "domain",
        nargs="?",
        help="domain to diagnose (omit with Instantly/bulk modes)",
    )
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
        "--instantly-ready",
        action="store_true",
        help="workspace readiness: diagnose Instantly sender domains + Instantly signals",
    )
    p.add_argument(
        "--ctd-host",
        action="append",
        help="custom tracking domain host to check via Instantly CTD status (repeatable)",
    )
    p.add_argument(
        "--from-instantly",
        action="store_true",
        help="bulk-diagnose unique sender domains from the Instantly workspace",
    )
    p.add_argument(
        "--pre-launch-gate",
        action="store_true",
        help="Instantly pre-launch gate (allowed_to_activate iff launch_verdict=ready)",
    )
    p.add_argument(
        "--campaign-desk",
        action="store_true",
        help="why Instantly campaigns are or are not sending (read-only)",
    )
    p.add_argument(
        "--reply-desk",
        action="store_true",
        help="Instantly unread count and latest received threads (read-only)",
    )
    p.add_argument(
        "--campaign-id",
        help="optional Instantly campaign id for --campaign-desk or --reply-desk",
    )
    p.add_argument(
        "--agency-export",
        action="store_true",
        help="with --instantly-ready: print white-label agency markdown",
    )
    p.add_argument(
        "--all-workspaces",
        action="store_true",
        help=(
            "with --instantly-ready: iterate Instantly workspace-group sub-workspaces "
            "(admin key + x-as-workspace; scopes: workspaces:read + group access)"
        ),
    )
    p.add_argument(
        "--fix-packet",
        choices=sorted(FIX_PACKET_PROVIDERS),
        help="print paste-ready registrar DNS fix packet after diagnose",
    )
    p.add_argument(
        "--bulk",
        metavar="FILE",
        help="diagnose many domains from a CSV or newline list",
    )
    p.add_argument(
        "--share-demo",
        action="store_true",
        help="offline Instantly gap demo: vitals all pass, launch still blocked (no API key)",
    )
    args = p.parse_args(argv)

    if args.share_demo:
        demo = run_share_demo()
        print(json.dumps(demo.to_dict(), indent=2) if args.json else render_share_demo(demo))
        return 0

    if args.instantly_compare:
        return _instantly_compare(as_json=args.json, domain=args.domain, use_llm=args.llm)

    if args.pre_launch_gate:
        return _pre_launch_gate(args)

    if args.campaign_desk:
        return _campaign_desk(args)

    if args.reply_desk:
        return _reply_desk(args)

    if args.instantly_ready:
        return _instantly_ready(args)

    if args.from_instantly or args.bulk:
        return _bulk(args)

    if not args.domain:
        p.error(
            "domain is required unless --share-demo, --instantly-compare, --instantly-ready, "
            "--pre-launch-gate, --campaign-desk, --reply-desk, --from-instantly, or --bulk is set"
        )

    if args.records:
        with open(args.records) as fh:
            resolver = FixtureResolver(json.load(fh))
    else:
        resolver = LiveResolver()

    explainer = LLMExplainer(anthropic_completer()) if args.llm else TemplateExplainer()
    esp_packs = list(args.esp_pack or ())
    if args.with_instantly and "instantly" not in esp_packs:
        esp_packs = ["instantly", *esp_packs]
    try:
        selectors = resolve_selectors(
            explicit=tuple(args.dkim_selector or ()),
            packs=tuple(esp_packs),
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
        payload = result.to_dict()
        if args.fix_packet:
            packet = build_fix_packet(
                args.domain, result.findings, provider=args.fix_packet,
            )
            payload["fix_packet"] = packet.to_dict()
        print(json.dumps(payload, indent=2))
    else:
        print(result.report)
        if result.signals and result.signals.instantly:
            print()
            rows = dicts_as_comparisons(result.signals.instantly)
            print(_instantly_markdown(rows, use_llm=args.llm))
        if args.fix_packet:
            print()
            print(build_fix_packet(
                args.domain, result.findings, provider=args.fix_packet,
            ).to_markdown())
    return 0


def _instantly_markdown(rows, *, use_llm: bool) -> str:
    if not use_llm:
        return render_comparison_markdown(rows)
    try:
        complete = anthropic_completer()
    except Exception:
        return render_comparison_markdown(rows)
    md, _src, _violations = rewrite_instantly_signals(rows, complete)
    return md


def _build_signals(args) -> DiagnosisSignals | None:
    if not (args.reputation or args.with_instantly):
        return None
    not_checked: list[str] = []
    instantly = None
    reputation = None
    if args.with_instantly:
        client = InstantlyClient()
        instantly = comparisons_as_dicts(
            compare_warmup_to_placement(client, domain=args.domain)
        )
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


def _resolver_from_args(args):
    if args.records:
        with open(args.records) as fh:
            return FixtureResolver(json.load(fh))
    return LiveResolver()


def _bulk(args) -> int:
    domains: list[str] = []
    if args.from_instantly:
        try:
            client = InstantlyClient()
            domains = unique_sender_domains(client.list_accounts())
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except InstantlyError as exc:
            print(
                f"Instantly API request failed (HTTP {exc.status}). "
                "No bulk domains were loaded.",
                file=sys.stderr,
            )
            return 2
        if not domains:
            print("No sending-account domains found in Instantly workspace.", file=sys.stderr)
            return 2
    if args.bulk:
        with open(args.bulk) as fh:
            from_file = parse_domain_list(fh.read())
        if args.from_instantly:
            # Union, Instantly first then file extras
            seen = set(domains)
            for d in from_file:
                if d not in seen:
                    domains.append(d)
                    seen.add(d)
        else:
            domains = from_file
    if not domains:
        print("No domains found for bulk diagnosis.", file=sys.stderr)
        return 2

    resolver = _resolver_from_args(args)
    explainer = LLMExplainer(anthropic_completer()) if args.llm else TemplateExplainer()
    esp_packs = list(args.esp_pack or ())
    if args.from_instantly and "instantly" not in esp_packs:
        esp_packs = ["instantly", *esp_packs]
    selectors = resolve_selectors(
        explicit=tuple(args.dkim_selector or ()),
        packs=tuple(esp_packs),
        defaults=DEFAULT_DKIM_SELECTORS,
    )

    signals_factory = None
    if args.with_instantly or args.from_instantly:
        try:
            client = InstantlyClient()
            all_cmp = compare_warmup_to_placement(client)

            def signals_factory(domain: str) -> DiagnosisSignals:
                filtered = [
                    c for c in all_cmp
                    if c.email.rsplit("@", 1)[-1] == domain
                ]
                return DiagnosisSignals(
                    instantly=comparisons_as_dicts(filtered),
                    reputation=None,
                    not_checked=["reputation"],
                )
        except (ValueError, InstantlyError):
            signals_factory = None

    report = run_bulk(
        domains, resolver, explainer, dkim_selectors=selectors, signals_factory=signals_factory,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.to_markdown())
    return 0


def _instantly_compare(*, as_json: bool, domain: str | None = None, use_llm: bool = False) -> int:
    try:
        client = InstantlyClient()
        reports = compare_warmup_to_placement(client, domain=domain)
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
        print(_instantly_markdown(reports, use_llm=use_llm))
    return 0


def _instantly_ready(args) -> int:
    try:
        client = InstantlyClient()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    resolver = _resolver_from_args(args)
    explainer = LLMExplainer(anthropic_completer()) if args.llm else TemplateExplainer()
    try:
        if getattr(args, "all_workspaces", False):
            agency = run_all_workspaces_readiness(
                client,
                resolver,
                explainer,
                ctd_hosts=list(args.ctd_host or ()),
                include_rich_signals=True,
            )
            if args.json:
                print(json.dumps(agency.to_dict(), indent=2))
            else:
                print(render_agency_workspaces_markdown(agency))
            return 0
        report = run_workspace_readiness(
            client,
            resolver,
            explainer,
            ctd_hosts=list(args.ctd_host or ()),
            include_rich_signals=True,
        )
    except InstantlyError as exc:
        print(
            f"Instantly API request failed (HTTP {exc.status}). "
            "No readiness report was produced.",
            file=sys.stderr,
        )
        return 2
    except ResolverError as exc:
        print(
            f"Could not complete DNS checks during readiness: {exc}",
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    elif getattr(args, "agency_export", False):
        print(render_agency_report(report))
    else:
        print(render_readiness_markdown(report))
    return 0


def _pre_launch_gate(args) -> int:
    try:
        client = InstantlyClient()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    resolver = _resolver_from_args(args)
    try:
        report = run_workspace_readiness(
            client,
            resolver,
            TemplateExplainer(),
            ctd_hosts=list(args.ctd_host or ()),
            include_rich_signals=True,
        )
        gate = build_pre_launch_gate(report, domain_filter=args.domain)
    except InstantlyError as exc:
        print(
            f"Instantly API request failed (HTTP {exc.status}). "
            "No pre-launch gate was produced.",
            file=sys.stderr,
        )
        return 2
    except ResolverError as exc:
        print(f"Could not complete DNS checks during gate: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(gate, indent=2))
    else:
        print(gate["markdown"])
    return 0 if gate.get("allowed_to_activate") else 3


def _instantly_client_or_exit() -> InstantlyClient | int:
    try:
        return InstantlyClient()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _campaign_desk(args) -> int:
    client = _instantly_client_or_exit()
    if isinstance(client, int):
        return client
    try:
        report = run_campaign_desk(client, campaign_id=args.campaign_id)
    except InstantlyError as exc:
        print(
            f"Instantly API request failed (HTTP {exc.status}). "
            "No campaign desk report was produced.",
            file=sys.stderr,
        )
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_campaign_desk_markdown(report))
    return 0 if report.verdict in ("sending", "idle") else 3


def _reply_desk(args) -> int:
    client = _instantly_client_or_exit()
    if isinstance(client, int):
        return client
    try:
        report = run_reply_desk(client, campaign_id=args.campaign_id)
    except InstantlyError as exc:
        print(
            f"Instantly API request failed (HTTP {exc.status}). "
            "No reply desk report was produced.",
            file=sys.stderr,
        )
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_reply_desk_markdown(report))
    return 0 if report.verdict == "clear" else 3


if __name__ == "__main__":
    sys.exit(main())
