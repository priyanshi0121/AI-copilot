"""JSON-file incident store. Simple, inspectable, demo-friendly — the state
the dashboard renders and the detector mutates is always visible in
data/incidents.json. Thread-safe (detector runs in a background thread)."""
import json
import os
import threading
from datetime import datetime, timezone

from .config import config


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IncidentStore:
    def __init__(self, path: str = None):
        self.path = path or os.path.join(config.data_dir, "incidents.json")
        self._lock = threading.RLock()
        self._incidents = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    self._incidents = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._incidents = []

    def _save(self):
        tmp = self.path + ".tmp"
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._incidents, fh, indent=2)
        os.replace(tmp, self.path)

    def _next_id(self) -> int:
        return max((i["id"] for i in self._incidents), default=0) + 1

    def create(self, service: str, kind: str, detected_value, threshold, details=None) -> dict:
        with self._lock:
            incident = {
                "id": self._next_id(),
                "service": service,
                "kind": kind,  # latency | error | down
                "status": "open",  # open | acknowledged | resolved
                "detected_value": detected_value,
                "threshold": threshold,
                "details": details or {},
                "started_at": utcnow(),
                "last_seen_at": utcnow(),
                "healthy_checks": 0,
                "priority_score": None,
                "cost_estimate": None,
                "root_cause": None,
                "confidence": None,
                "correlated_deploy": None,
                "blast_radius": None,
                "root_cause_path": None,
                "runbook": None,
                "ai_engine": None,
                "resolved_at": None,
                "resolution": None,
                "postmortem": None,
                "timeline": [{"ts": utcnow(), "event": f"Incident detected: {kind} on {service}"}],
            }
            self._incidents.append(incident)
            self._save()
            return incident

    def get(self, incident_id: int):
        with self._lock:
            for incident in self._incidents:
                if incident["id"] == incident_id:
                    return dict(incident)
        return None

    def update(self, incident_id: int, **fields):
        with self._lock:
            for incident in self._incidents:
                if incident["id"] == incident_id:
                    incident.update(fields)
                    self._save()
                    return dict(incident)
        return None

    def add_timeline(self, incident_id: int, event: str):
        with self._lock:
            for incident in self._incidents:
                if incident["id"] == incident_id:
                    incident["timeline"].append({"ts": utcnow(), "event": event})
                    self._save()
                    return

    def list(self, status: str = None) -> list:
        with self._lock:
            incidents = [dict(i) for i in self._incidents]
        if status:
            incidents = [i for i in incidents if i["status"] == status]
        return sorted(incidents, key=lambda i: i["id"], reverse=True)

    def open_incidents(self) -> list:
        return [i for i in self.list() if i["status"] in ("open", "acknowledged")]

    def find_open(self, service: str, kind: str):
        for incident in self.open_incidents():
            if incident["service"] == service and incident["kind"] == kind:
                return incident
        return None

    def ack(self, incident_id: int):
        inc = self.update(incident_id, status="acknowledged")
        if inc:
            self.add_timeline(incident_id, "Incident acknowledged by engineer")
        return inc

    def resolve(self, incident_id: int, resolution: str):
        inc = self.update(incident_id, status="resolved", resolved_at=utcnow(), resolution=resolution)
        if inc:
            self.add_timeline(incident_id, f"Incident resolved: {resolution}")
        return inc

    def clear(self):
        """Wipe all incidents (demo reset)."""
        with self._lock:
            self._incidents = []
            self._save()
