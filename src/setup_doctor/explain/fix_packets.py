"""Paste-ready DNS fix packets + versioned registrar playbooks.

Templates only. Record strings must ground in Finding.fix / evidence —
verify_fix_packet rejects invented records not present in Findings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from setup_doctor.core.models import Finding

PROVIDERS = ("cloudflare", "namecheap", "godaddy", "google_domains")
PLAYBOOK_VERSION = "1.0"

_RECORD_RE = re.compile(
    r"\b(?:v=spf1\b[^\n`]*|v=DMARC1\b[^\n`]*|k=rsa[^\n`]*|"
    r"(?:TXT|CNAME|MX)\s+[^\n`]+)",
    re.I,
)


@dataclass
class FixPacket:
    provider: str
    playbook_version: str
    domain: str
    steps: list[dict[str, str]] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "playbook_version": self.playbook_version,
            "domain": self.domain,
            "steps": list(self.steps),
            "finding_ids": list(self.finding_ids),
            "notes": list(self.notes),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# DNS fix packet ({self.provider})",
            "",
            f"Domain: `{self.domain}` · playbook `{self.playbook_version}`",
            "",
            "Grounded in Setup Doctor Findings only — do not invent records.",
            "",
        ]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"## Step {i}: {step.get('title', 'Fix')}")
            lines.append("")
            if step.get("finding_id"):
                lines.append(f"- Finding: `{step['finding_id']}`")
            if step.get("ui_path"):
                lines.append(f"- In {self.provider}: {step['ui_path']}")
            if step.get("action"):
                lines.append(f"- Action: {step['action']}")
            if step.get("record"):
                lines.append("")
                lines.append("```")
                lines.append(step["record"])
                lines.append("```")
            lines.append("")
        for note in self.notes:
            lines.append(f"> {note}")
        lines.append("")
        return "\n".join(lines)


_UI_PATH = {
    "cloudflare": "DNS → Records → Add record",
    "namecheap": "Domain List → Manage → Advanced DNS",
    "godaddy": "DNS → Manage Zones → Add",
    "google_domains": "DNS → Custom records (or Squarespace Domains DNS)",
}


def _record_hint(finding: Finding) -> str:
    for key in ("record", "expected", "suggested", "value"):
        if key in finding.evidence and finding.evidence[key].strip():
            return finding.evidence[key].strip()
    # Pull fenced/backtick-ish snippets from fix text when present.
    fix = finding.fix or ""
    m = re.search(r"`([^`]+)`", fix)
    if m and ("v=spf1" in m.group(1) or "v=DMARC1" in m.group(1) or "k=" in m.group(1)):
        return m.group(1).strip()
    # Common SPF/DMARC lines embedded without backticks
    for pat in (r"(v=spf1[^\n]+)", r"(v=DMARC1[^\n]+)"):
        m2 = re.search(pat, fix, re.I)
        if m2:
            return m2.group(1).strip()
    return ""


def _action_for(finding: Finding) -> str:
    fid = finding.id.upper()
    if "SPF" in fid:
        return "Create or replace the SPF TXT record at the domain apex (@)."
    if "DKIM" in fid:
        return (
            "Publish the DKIM TXT/CNAME at `<selector>._domainkey` "
            "(use Instantly/ESP selector; guessed packs are not proof of absence)."
        )
    if "DMARC" in fid:
        return "Create or update `_dmarc` TXT (start with p=none + rua, then tighten)."
    if "MX" in fid:
        return "Add MX records for your mailbox provider."
    return finding.fix


def build_fix_packet(
    domain: str,
    findings: list[Finding],
    *,
    provider: str = "cloudflare",
) -> FixPacket:
    provider_key = provider.strip().lower().replace(" ", "_")
    if provider_key not in PROVIDERS:
        raise ValueError(
            f"unknown fix-packet provider {provider!r}; known: {', '.join(PROVIDERS)}"
        )
    ui = _UI_PATH[provider_key]
    steps: list[dict[str, str]] = []
    ids: list[str] = []
    for f in findings:
        ids.append(f.id)
        record = _record_hint(f)
        steps.append({
            "finding_id": f.id,
            "title": f.title,
            "ui_path": ui,
            "action": _action_for(f),
            "record": record,
            "why": f.why,
            "fix": f.fix,
        })
    notes = [
        "Paste records exactly from Findings / Instantly ESP docs — do not invent values.",
        "DKIM selector guesses are not definitive absence proof.",
    ]
    if provider_key == "google_domains":
        notes.append(
            "Google Domains migrated to Squarespace; UI labels may say Squarespace Domains."
        )
    return FixPacket(
        provider=provider_key,
        playbook_version=PLAYBOOK_VERSION,
        domain=domain,
        steps=steps,
        finding_ids=ids,
        notes=notes,
    )


def verify_fix_packet(packet: FixPacket, findings: list[Finding]) -> list[str]:
    """Reject packets that cite unknown finding ids or invent record strings."""
    violations: list[str] = []
    by_id = {f.id: f for f in findings}
    allowed_records: set[str] = set()
    for f in findings:
        hint = _record_hint(f)
        if hint:
            allowed_records.add(hint.lower())
        for chunk in re.findall(r"`([^`]+)`", f.fix or ""):
            allowed_records.add(chunk.lower())
        for v in f.evidence.values():
            if v.strip():
                allowed_records.add(v.strip().lower())

    for step in packet.steps:
        fid = step.get("finding_id") or ""
        if fid and fid not in by_id:
            violations.append(f"unknown finding id [{fid}]")
        record = (step.get("record") or "").strip()
        if record and record.lower() not in allowed_records:
            # Allow empty; non-empty must be grounded
            # Also allow substring match against finding.fix
            grounded = False
            f = by_id.get(fid)
            if f and record.lower() in (f.fix or "").lower():
                grounded = True
            if f and any(record.lower() in (v or "").lower() for v in f.evidence.values()):
                grounded = True
            if not grounded:
                violations.append(f"ungrounded record for [{fid}]: {record[:80]}")

    # Scan markdown-ish free text if present in actions
    blob = " ".join(
        f"{s.get('action', '')} {s.get('record', '')} {s.get('fix', '')}"
        for s in packet.steps
    )
    for m in _RECORD_RE.finditer(blob):
        snippet = m.group(0).strip().lower()
        if allowed_records and not any(snippet in a or a in snippet for a in allowed_records):
            # Only flag SPF/DMARC-looking inventions
            if snippet.startswith("v=spf1") or snippet.startswith("v=dmarc1"):
                if not any(snippet in a or a in snippet for a in allowed_records):
                    violations.append(f"ungrounded DNS-looking string: {m.group(0)[:80]}")

    return violations


def playbook_snippet(provider: str) -> dict[str, Any]:
    """Versioned registrar playbook (no live scrape)."""
    provider_key = provider.strip().lower().replace(" ", "_")
    if provider_key not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    return {
        "provider": provider_key,
        "playbook_version": PLAYBOOK_VERSION,
        "ui_path": _UI_PATH[provider_key],
        "steps_overview": [
            "Open DNS management for the domain",
            "Apply each Setup Doctor Finding step from the fix packet",
            "Wait for TTL propagation, then re-run diagnose / pre_launch_gate",
        ],
        "notes": [
            "Playbooks are curated in-repo; Setup Doctor never scrapes registrar UIs.",
            "Instantly owns placement/warmup; Setup Doctor owns DNS Findings.",
        ],
    }
