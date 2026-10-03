"""Provider-agnostic AI client: anthropic | zai | openai | ollama — chosen via
AI_PROVIDER in .env. With no API key configured, everything still works via a
deterministic rule-based engine (clearly labelled), so the copilot is never
blocked on a key and the demo always runs."""
import json
import re

from .config import config

OPENAI_COMPATIBLE = {"zai", "openai", "ollama"}


class AIClient:
    def __init__(self, cfg=config):
        self.cfg = cfg

    # ---- provider plumbing -------------------------------------------------

    def _key_for(self, provider: str) -> str:
        return {
            "anthropic": self.cfg.anthropic_api_key,
            "zai": self.cfg.zai_api_key,
            "openai": self.cfg.openai_api_key,
            "ollama": "local",  # no key needed
        }.get(provider, "")

    def _base_url_for(self, provider: str) -> str:
        return {
            "zai": self.cfg.zai_base_url,
            "openai": None,  # official API
            "ollama": self.cfg.ollama_base_url,
        }.get(provider)

    def _model_for(self, provider: str) -> str:
        return {
            "anthropic": self.cfg.anthropic_model,
            "zai": self.cfg.zai_model,
            "openai": self.cfg.openai_model,
            "ollama": self.cfg.ollama_model,
        }.get(provider, "")

    def provider_name(self) -> str:
        return self.cfg.ai_provider

    def available(self) -> bool:
        provider = self.cfg.ai_provider
        if provider == "anthropic":
            return bool(self.cfg.anthropic_api_key)
        if provider in OPENAI_COMPATIBLE:
            return True if provider == "ollama" else bool(self.cfg.openai_api_key or self._key_for(provider))
        return False

    def complete(self, system: str, prompt: str, max_tokens: int = 800) -> str:
        provider = self.cfg.ai_provider
        if provider == "anthropic":
            import anthropic

            client = anthropic.Anthropic(api_key=self.cfg.anthropic_api_key)
            message = client.messages.create(
                model=self._model_for(provider),
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text

        if provider in OPENAI_COMPATIBLE:
            from openai import OpenAI

            kwargs = {"api_key": self._key_for(provider)}
            base_url = self._base_url_for(provider)
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(**kwargs)
            response = client.chat.completions.create(
                model=self._model_for(provider),
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content

        raise ValueError(f"Unknown AI_PROVIDER: {provider}")

    # ---- structured outputs ------------------------------------------------

    def _extract_json(self, text: str):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def diagnose(self, context: dict) -> dict:
        """context: {incident, correlation, blast_radius, root_cause_path}.
        Returns {root_cause, confidence, reasoning, runbook, engine}."""
        if self.available():
            try:
                return self._ai_diagnose(context)
            except Exception as exc:  # network, quota, parse — degrade gracefully
                fallback = rule_based_diagnose(context)
                fallback["engine"] = f"rule-based (AI call failed: {type(exc).__name__})"
                return fallback
        return rule_based_diagnose(context)

    def _ai_diagnose(self, context: dict) -> dict:
        incident = context["incident"]
        correlation = context.get("correlation")
        blast = context.get("blast_radius") or []

        corr_text = (
            correlation["explanation"] if correlation else "No deploys within the correlation window."
        )
        prompt = f"""You are an AIOps root-cause analyst for a small microservice system.

INCIDENT
- Service: {incident['service']}
- Type: {incident['kind']} anomaly
- Observed: {incident['detected_value']:.3f} (threshold {incident['threshold']})
- Dependencies of this service: {', '.join(incident.get('dependencies', [])) or 'none'}
- Blast radius (services affected if this stays broken): {', '.join(sum(blast, [])) or 'none'}

DEPLOY CORRELATION
{corr_text}

Respond with ONLY a JSON object, no markdown fences:
{{
  "root_cause": "1-2 sentences naming the most likely cause",
  "confidence": 0-100,
  "reasoning": "1-2 sentences justifying the confidence",
  "runbook": ["step 1", "step 2", "step 3"]
}}
Keep the runbook to 3-5 concrete, safe steps (restart / rollback / scale / verify)."""

        system = (
            "You are a precise SRE assistant. Answer with a single valid JSON object. "
            "Never invent metrics you were not given."
        )
        text = self.complete(system, prompt)
        parsed = self._extract_json(text) or {}

        root_cause = str(parsed.get("root_cause") or "Unclear — manual investigation needed.").strip()
        try:
            confidence = max(0, min(100, int(parsed.get("confidence", 50))))
        except (TypeError, ValueError):
            confidence = 50
        runbook = [str(s) for s in (parsed.get("runbook") or [])][:5]

        return {
            "root_cause": root_cause,
            "confidence": confidence,
            "reasoning": str(parsed.get("reasoning") or "").strip(),
            "runbook": runbook or rule_based_diagnose(context)["runbook"],
            "engine": f"{self.cfg.ai_provider} ({self._model_for(self.cfg.ai_provider)})",
        }

    def postmortem(self, incident: dict) -> str:
        """AI-polished postmortem; falls back to the template on any problem."""
        if not self.available():
            return None
        try:
            prompt = (
                "Write a concise incident postmortem in markdown for this resolved incident.\n"
                f"Service: {incident['service']}\nType: {incident['kind']}\n"
                f"Detected value: {incident['detected_value']}\nRoot cause: {incident.get('root_cause')}\n"
                f"Correlated deploy: {incident.get('correlated_deploy')}\n"
                f"Resolution: {incident.get('resolution')}\n"
                f"Cost estimate: {incident.get('cost_estimate')}\n"
                "Sections: Summary, Timeline, Impact, Root Cause, What Went Well, Action Items (3 bullets max each)."
            )
            return self.complete(
                "You are an SRE writing a blameless postmortem. Be factual and concise.",
                prompt,
                max_tokens=900,
            )
        except Exception:
            return None


def rule_based_diagnose(context: dict) -> dict:
    """Deterministic fallback: reason from the correlation + graph data we
    already computed. Runs with zero API keys."""
    incident = context["incident"]
    correlation = context.get("correlation")
    service = incident["service"]

    if incident["kind"] == "down":
        return {
            "root_cause": (
                f"{service} is not responding at all — the container is stopped, crashed, "
                f"or unreachable from the monitoring stack."
            ),
            "confidence": 80,
            "reasoning": "Rule-based engine: a failed Prometheus scrape means the service answers no requests.",
            "runbook": [
                f"Check container status and last logs for {service}",
                f"Restart/resume {service} from the dashboard",
                "Verify /health returns 200 after startup",
                "If it crash-loops, roll back the last deploy and investigate",
            ],
            "engine": "rule-based fallback",
        }

    if correlation:
        deploy = correlation["deploy"]
        root_cause = (
            f"Deploy #{deploy['id']} ({deploy['version']}) to {deploy['service']} "
            f"{correlation['age_minutes']:.0f} min before the alert is the most likely cause "
            f"— the change window lines up with symptom onset."
        )
        runbook = [
            f"Verify what changed in {deploy['service']} {deploy['version']} ({deploy['note']})",
            f"Roll back the bad change on {deploy['service']} (dashboard Rollback or redeploy previous version)",
            f"Restart {deploy['service']} to clear in-memory state",
            f"Confirm {service} metrics return below threshold within 2 checks",
        ]
    elif incident["kind"] == "latency":
        root_cause = (
            f"No recent deploys correlate; sustained latency on {service} suggests resource saturation "
            f"or a slow downstream dependency."
        )
        runbook = [
            f"Check {service} CPU/memory and connection-pool saturation",
            "Inspect the slowest downstream dependency and its timeouts",
            f"Restart {service} to clear any wedged workers",
            "If pressure persists, scale the service and re-check latency",
        ]
    else:
        root_cause = (
            f"No recent deploys correlate; rising error rate on {service} points to a runtime fault "
            f"(bad config, exhausted pool, or failing downstream call)."
        )
        runbook = [
            f"Inspect {service} logs for the failing operation",
            "Check the health of its downstream dependencies",
            f"Restart {service}; if errors persist, roll back the last config change",
            "Verify error rate returns to baseline before closing",
        ]

    return {
        "root_cause": root_cause,
        "confidence": 60 if correlation else 40,
        "reasoning": "Rule-based engine: deploy-window correlation and dependency-graph heuristics (no AI key configured).",
        "runbook": runbook,
        "engine": "rule-based fallback",
    }
