"""Background detection loop: polls Prometheus, opens/updates/resolves
incidents, and enriches each new incident with the full intelligence pipeline:

  correlate → DFS root-cause path → BFS blast radius → cost estimate
  → AI (or rule-based) diagnosis + runbook → priority score
"""
import threading
import traceback

from . import correlation, cost, dependency_graph, metrics
from .ai_client import AIClient
from .config import config
from .incidents import utcnow
from .postmortem import generate_postmortem
from .prioritizer import priority_score
from .runbook import build_runbook


class DetectionLoop(threading.Thread):
    def __init__(self, store, ai: AIClient = None):
        super().__init__(daemon=True, name="detection-loop")
        self.store = store
        self.ai = ai or AIClient()
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:
                traceback.print_exc()
            self._stop.wait(config.check_interval_s)

    def check_once(self):
        for svc in metrics.MONITORED_SERVICES:
            up = metrics.service_up(svc["job"])
            if up is not None and up < 1:
                # scrape target down: manage an availability incident and skip
                # rate-based kinds (their data is stale/missing while down)
                self._evaluate_down(svc, up)
                continue
            latency = metrics.avg_latency(svc["histogram"])
            error_rate = metrics.error_rate(svc["counter"])

            self._evaluate(svc, "latency", latency, config.latency_threshold_s, above_is_bad=True)
            self._evaluate(svc, "error", error_rate, config.error_rate_threshold, above_is_bad=True)
            self._settle_down_incident(svc)

    def _evaluate_down(self, svc: dict, up: float):
        service = svc["name"]
        existing = self.store.find_open(service, "down")
        rpm = metrics.request_rate(svc["counter"]) * 60
        if existing:
            self.store.update(
                existing["id"],
                last_seen_at=utcnow(),
                healthy_checks=0,
                cost_estimate=cost.estimate_cost({**existing, "kind": "down"}, requests_per_min=rpm),
            )
            return
        incident = self.store.create(service, "down", detected_value=up, threshold=1.0,
                                     details={"reason": "prometheus scrape target unreachable"})
        print(f"[detector] 🚨 incident #{incident['id']}: service {service} is DOWN")
        self._enrich(svc, incident)

    def _settle_down_incident(self, svc: dict):
        existing = self.store.find_open(svc["name"], "down")
        if not existing:
            return
        healthy = existing.get("healthy_checks", 0) + 1
        if healthy >= config.resolve_after_checks:
            incident = self.store.resolve(existing["id"], f"auto-resolved: service back up for {healthy} checks")
            self.store.update(existing["id"], postmortem=generate_postmortem(incident, self.ai))
            print(f"[detector] incident #{existing['id']} (down) auto-resolved; postmortem attached")
        else:
            self.store.update(existing["id"], healthy_checks=healthy, last_seen_at=utcnow())

    def _evaluate(self, svc: dict, kind: str, value, threshold: float, above_is_bad: bool):
        service = svc["name"]
        bad = value is not None and value > threshold
        existing = self.store.find_open(service, kind)

        if bad:
            if existing:
                rpm = metrics.request_rate(svc["counter"]) * 60
                self.store.update(
                    existing["id"],
                    detected_value=value,
                    last_seen_at=utcnow(),
                    healthy_checks=0,
                    cost_estimate=cost.estimate_cost(
                        {**existing, "detected_value": value}, requests_per_min=rpm
                    ),
                )
            else:
                self._open_incident(svc, kind, value, threshold)
            return

        if value is None:
            # no data yet (fresh scrape target, prometheus down, traffic just
            # started) — NOT healthy, just unknown: never count toward resolve
            return

        # healthy — count consecutive healthy checks for auto-resolution
        if existing and existing["status"] != "resolved":
            healthy = existing.get("healthy_checks", 0) + 1
            if healthy >= config.resolve_after_checks:
                incident = self.store.resolve(existing["id"], f"auto-resolved: {kind} back under threshold for {healthy} checks")
                self.store.add_timeline(existing["id"], "Generating postmortem…")
                self.store.update(existing["id"], postmortem=generate_postmortem(incident, self.ai))
                print(f"[detector] incident #{existing['id']} auto-resolved; postmortem attached")
            else:
                self.store.update(existing["id"], healthy_checks=healthy, last_seen_at=utcnow())

    def _open_incident(self, svc: dict, kind: str, value, threshold: float):
        service = svc["name"]
        incident = self.store.create(service, kind, value, threshold)
        print(f"[detector] 🚨 incident #{incident['id']}: {kind} on {service} = {value:.3f} (threshold {threshold})")
        self._enrich(svc, incident)

    def _enrich(self, svc: dict, incident: dict):
        """Full intelligence pipeline for a freshly opened incident."""
        service = incident["service"]
        kind = incident["kind"]
        value = incident["detected_value"]
        threshold = incident["threshold"]

        # --- intelligence pipeline ------------------------------------------
        correlation_result = correlation.correlate(service)
        root_path = dependency_graph.dfs_root_cause_path(service)
        blast = dependency_graph.bfs_blast_radius(service)
        cycles = dependency_graph.find_cycles()
        rpm = metrics.request_rate(svc["counter"]) * 60
        cost_estimate = cost.estimate_cost(incident, requests_per_min=rpm)

        diagnosis = self.ai.diagnose(
            {
                "incident": {
                    "service": service,
                    "kind": kind,
                    "detected_value": value,
                    "threshold": threshold,
                    "dependencies": dependency_graph.dependencies_of(service),
                },
                "correlation": correlation_result,
                "blast_radius": blast,
                "root_cause_path": root_path,
            }
        )

        score = priority_score({**incident, "cost_estimate": cost_estimate})

        fields = {
            "correlated_deploy": correlation_result,
            "root_cause_path": root_path,
            "blast_radius": blast,
            "dependency_cycles": cycles,
            "cost_estimate": cost_estimate,
            "root_cause": diagnosis["root_cause"],
            "confidence": diagnosis["confidence"],
            "ai_reasoning": diagnosis.get("reasoning", ""),
            "ai_engine": diagnosis["engine"],
            "runbook": build_runbook(diagnosis["runbook"]),
            "priority_score": score,
        }
        self.store.update(incident["id"], **fields)
        self.store.add_timeline(
            incident["id"],
            f"Enriched: {diagnosis['engine']} · confidence {diagnosis['confidence']}% · "
            f"correlation {'found' if correlation_result else 'none'} · priority ${score}/fix-min",
        )
        print(f"[detector] incident #{incident['id']} enriched via {diagnosis['engine']} (confidence {diagnosis['confidence']}%)")
