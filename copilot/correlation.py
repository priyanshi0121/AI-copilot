"""Deploy history + alert-to-deploy correlation with confidence scoring.

"The alert started N minutes after deploy #X (confidence: Y%)" — the core
root-cause analysis feature. Deploys live in data/deploys.json; a synthetic
history is seeded on first run so the demo works out of the box, and new
deploys can be recorded from the dashboard or POST /deploys."""
import json
import os
import threading
from datetime import datetime, timedelta, timezone

from .config import config
from .dependency_graph import dependencies_of

_lock = threading.RLock()  # reentrant: record_deploy() calls list_deploys() under the lock


def _deploys_path() -> str:
    return os.path.join(config.data_dir, "deploys.json")


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _seed():
    """Synthetic recent deploy history (relative to first-run time)."""
    now = datetime.now(timezone.utc)
    seed = _seed_history(now)
    os.makedirs(config.data_dir, exist_ok=True)
    with open(_deploys_path(), "w", encoding="utf-8") as fh:
        json.dump(seed, fh, indent=2)
    return seed


def list_deploys() -> list:
    with _lock:
        if not os.path.exists(_deploys_path()):
            return _seed()
        try:
            with open(_deploys_path(), "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            # transient read failure (e.g. slow file provider, concurrent
            # atomic replace) — retry once; never clobber real history with
            # seeds just because one read hiccupped
            try:
                with open(_deploys_path(), "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                now = datetime.now(timezone.utc)
                return _seed_history(now)


def _seed_history(now: datetime) -> list:
    return [
        {
            "id": 1,
            "service": "order-service",
            "version": "v1.3.8",
            "note": "routine dependency bump",
            "author": "amara",
            "deployed_at": (now - timedelta(hours=3)).isoformat(timespec="seconds"),
        },
        {
            "id": 2,
            "service": "inventory-service",
            "version": "v0.9.1",
            "note": "cache TTL tweak",
            "author": "kenji",
            "deployed_at": (now - timedelta(minutes=95)).isoformat(timespec="seconds"),
        },
        {
            "id": 3,
            "service": "payment-service",
            "version": "v1.4.2",
            "note": "autoscaler + connection pool config change",
            "author": "priya",
            "deployed_at": (now - timedelta(minutes=20)).isoformat(timespec="seconds"),
        },
    ]


def record_deploy(service: str, version: str = None, note: str = "", author: str = "dashboard") -> dict:
    with _lock:
        deploys = list_deploys()
        deploy = {
            "id": max((d["id"] for d in deploys), default=0) + 1,
            "service": service,
            "version": version or f"v1.4.{len(deploys) + 3}",
            "note": note or "deploy recorded from dashboard",
            "author": author,
            "deployed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        deploys.append(deploy)
        with open(_deploys_path(), "w", encoding="utf-8") as fh:
            json.dump(deploys, fh, indent=2)
        return deploy


def correlate(alert_service: str, alert_time: datetime = None, window_min: int = None) -> dict:
    """Most probable causal deploy for an alert, with a confidence percentage.

    A deploy to the alerting service OR to anything it depends on can be the
    cause (a bad payment-service deploy shows up as order-service symptoms).
    Confidence: base 55, +30 if the deploy is <5 min old, +20 if <15 min,
    +10 if within the window, +10 for a direct deploy to the alerting service.
    """
    alert_time = alert_time or datetime.now(timezone.utc)
    window_min = window_min or config.deploy_window_min
    cutoff = alert_time - timedelta(minutes=window_min)
    candidate_services = {alert_service} | set(dependencies_of(alert_service))

    deploys = list_deploys()
    candidates = []
    for deploy in deploys:
        if deploy["service"] not in candidate_services:
            continue
        deployed_at = _parse_ts(deploy["deployed_at"])
        if deployed_at.tzinfo is None:
            deployed_at = deployed_at.replace(tzinfo=timezone.utc)
        age_min = (alert_time - deployed_at).total_seconds() / 60
        if 0 <= age_min <= window_min:
            candidates.append((deploy, age_min))

    if not candidates:
        return None

    # most recent deploy is the likeliest culprit
    deploy, age_min = min(candidates, key=lambda c: c[1])

    confidence = 55
    if age_min <= 5:
        confidence += 30
    elif age_min <= 15:
        confidence += 20
    else:
        confidence += 10
    if deploy["service"] == alert_service:
        confidence += 10
    confidence = min(confidence, 95)

    relation = "directly" if deploy["service"] == alert_service else f"via its dependency {deploy['service']}"
    return {
        "deploy": deploy,
        "age_minutes": round(age_min, 1),
        "confidence": confidence,
        "explanation": (
            f"Alert on {alert_service} started {age_min:.0f} min after deploy #{deploy['id']} "
            f"({deploy['version']} to {deploy['service']}, {relation}) — confidence {confidence}%."
        ),
    }
