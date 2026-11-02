"""Command line entry point.

    python -m setup_doctor example.com                    # live DNS, template explanation
    python -m setup_doctor example.com --llm              # live DNS, LLM explanation (needs key)
    python -m setup_doctor broken.test --records examples/broken.json
    python -m setup_doctor --instantly-compare            # Instantly warmup vs placement (read-only)
"""
from __future__ import annotations

import argparse
import json
import sys

from .checks import DEFAULT_DKIM_SELECTORS
from .explain import LLMExplainer, TemplateExplainer, anthropic_completer
from .graph import diagnose
from .instantly_client import InstantlyClient, InstantlyError
from .instantly_compare import compare_warmup_to_placement, render_comparison_markdown
from .resolver import FixtureResolver, LiveResolver, ResolverError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="setup-doctor", description="Diagnose cold-email DNS setup.")
    p.add_argument("domain", nargs="?", help="domain to diagnose (omit with --instantly-compare)")
    p.add_argument("--records", help="JSON file of frozen DNS records (offline mode)")
    p.add_argument("--dkim-selector", action="append", help="extra DKIM selector to try (repeatable)")
    p.add_argument("--llm", action="store_true", help="use the Anthropic SDK for the explanation")
    p.add_argument("--json", action="store_true", help="print findings as JSON instead of a report")
    p.add_argument(
        "--instantly-compare",
        action="store_true",
        help="compare Instantly warmup scores to inbox-placement tests (read-only API v2)",
    )
    args = p.parse_args(argv)

    if args.instantly_compare:
        return _instantly_compare(as_json=args.json)

    if not args.domain:
        p.error("domain is required unless --instantly-compare is set")

    if args.records:
        with open(args.records) as fh:
            resolver = FixtureResolver(json.load(fh))
    else:
        resolver = LiveResolver()

    explainer = LLMExplainer(anthropic_completer()) if args.llm else TemplateExplainer()
    selectors = tuple(args.dkim_selector or ()) + DEFAULT_DKIM_SELECTORS
    try:
        if isinstance(resolver, LiveResolver) and not resolver.domain_exists(args.domain):
            print(f"{args.domain} does not exist in DNS (NXDOMAIN), so there is nothing to diagnose.\n"
                  "Check the spelling and that the domain is registered. If you are sure it exists, "
                  "your resolver may be filtering it; try again from another network.", file=sys.stderr)
            return 2
        state = diagnose(args.domain, resolver, explainer, selectors)
    except ResolverError as exc:
        print(f"Could not complete the DNS checks: {exc}\n"
              "No diagnosis was produced (an outage is not the same as missing records).", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([f.to_dict() for f in state["findings"]], indent=2))
    else:
        print(state["report"])
    return 0


def _instantly_compare(*, as_json: bool) -> int:
    """Read-only Instantly API v2: warmup score vs inbox placement.

    Requires INSTANTLY_API_KEY. Optional INSTANTLY_USE_MOCK=true for the documented
    mock server. Real predictive claims need a real Instantly workspace.
    """
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
