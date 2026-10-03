"""Auto-generated postmortems for resolved incidents. The AI (when configured)
polishes the narrative; a deterministic template guarantees one always exists."""
from datetime import datetime, timezone

from .ai_client import AIClient


def _duration_minutes(incident: dict) -> float:
    started = datetime.fromisoformat(incident["started_at"])
    resolved = datetime.fromisoformat(incident["resolved_at"])
    return round((resolved - started).total_seconds() / 60, 1)


def template_postmortem(incident: dict) -> str:
    cost = incident.get("cost_estimate") or {}
    deploy = (incident.get("correlated_deploy") or {}).get("deploy") or {}
    lines = [
        f"# Postmortem — incident #{incident['id']} ({incident['service']} {incident['kind']})",
        "",
        "## Summary",
        f"{incident['service'].capitalize()} exceeded its {incident['kind']} threshold "
        f"(observed {incident['detected_value']}, threshold {incident['threshold']}). "
        + (f"Root cause attributed to deploy #{deploy.get('id')} ({deploy.get('version')}). " if deploy else "")
        + f"Resolved via: {incident.get('resolution')}.",
        "",
        "## Timeline",
        f"- {incident['started_at']} — anomaly detected",
    ]
    for entry in incident.get("timeline", []):
        lines.append(f"- {entry['ts']} — {entry['event']}")
    lines += [
        f"- {incident['resolved_at']} — resolved",
        "",
        "## Impact",
        f"- Duration: {_duration_minutes(incident)} min",
        f"- Estimated cost impact: ${cost.get('per_hour_usd', 0)}/hr (projected 24h: ${cost.get('projected_24h_usd', 0)})",
        f"- Blast radius: {incident.get('blast_radius') or 'n/a'}",
        "",
        "## Root Cause",
        incident.get("root_cause") or "Not determined.",
        "",
        "## What Went Well",
        "- Detection-to-diagnosis was fully automated (correlation + runbook draft).",
        "",
        "## Action Items",
        "- Add a regression test covering the fault injected/observed here.",
        "- Tighten the deploy canary window for this service.",
        "- Review alert thresholds against this incident's observed values.",
    ]
    return "\n".join(lines)


def generate_postmortem(incident: dict, ai: AIClient = None) -> str:
    ai = ai or AIClient()
    polished = ai.postmortem(incident)
    return polished or template_postmortem(incident)
