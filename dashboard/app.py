"""AIOps Copilot dashboard: one Flask process that renders incident state and
runs the detection loop in a background thread. Also exposes the chaos
triggers, deploy recording, and sandboxed remediation actions."""
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for

from copilot import actions as copilot_actions
from copilot import correlation, metrics, prioritizer
from copilot.ai_client import AIClient
from copilot.clustering import cluster_incidents
from copilot.config import config
from copilot.dependency_graph import MONITORED_SERVICES as GRAPH_SERVICES
from copilot.dependency_graph import find_cycles
from copilot.detector import DetectionLoop
from copilot.incidents import IncidentStore

store = IncidentStore()
ai = AIClient()
detector = None
_detector_lock = threading.Lock()


def start_detector():
    global detector
    with _detector_lock:
        if detector is None or not detector.is_alive():
            detector = DetectionLoop(store, ai)
            detector.start()


app = Flask(__name__)


@app.template_filter("ago")
def ago_filter(ts: str) -> str:
    """Human-friendly relative time for timestamps."""
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    except (ValueError, TypeError):
        return ts or ""
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m ago"
    return f"{int(seconds // 86400)}d ago"


def _chaos_status(service_entry: dict):
    url = getattr(config, service_entry["url_key"])
    try:
        resp = requests.get(f"{url}/chaos/status", timeout=2)
        if resp.ok:
            return resp.json().get("chaos", {})
    except requests.RequestException:
        pass
    return None


def _sparkline(values: list, threshold: float, w: int = 230, h: int = 44, pad: int = 3):
    """Normalize latency samples into SVG polyline points + a threshold line."""
    if len(values) < 2:
        return None
    vmax = max(max(values), threshold) * 1.15 or 1.0
    step = (w - 2 * pad) / (len(values) - 1)
    pts = " ".join(
        f"{pad + i * step:.1f},{h - pad - (v / vmax) * (h - 2 * pad):.1f}"
        for i, v in enumerate(values)
    )
    ty = h - pad - (threshold / vmax) * (h - 2 * pad)
    latest_over = values[-1] > threshold
    return {"points": pts, "threshold_y": f"{ty:.1f}", "over": latest_over, "w": w, "h": h}


def collect_state() -> dict:
    incidents = store.list()
    open_incidents = [i for i in incidents if i["status"] in ("open", "acknowledged")]
    services = []
    for svc in metrics.MONITORED_SERVICES:
        series = metrics.latency_series(svc["histogram"])
        services.append(
            {
                "name": svc["name"],
                "up": metrics.service_up(svc["job"]),
                "latency": metrics.avg_latency(svc["histogram"]),
                "error_rate": metrics.error_rate(svc["counter"]),
                "chaos": _chaos_status(svc),
                "spark": _sparkline(series, config.latency_threshold_s),
            }
        )
    return {
        "services": services,
        "incidents": incidents,
        "open_incidents": open_incidents,
        "clusters": cluster_incidents(open_incidents),
        "plan": prioritizer.prioritize(open_incidents),
        "deploys": correlation.list_deploys()[-6:][::-1],
        "deploy_count": len(correlation.list_deploys()),
        "ai_mode": (
            f"{ai.provider_name()} — key configured"
            if ai.available()
            else f"{ai.provider_name()} — NO KEY: rule-based fallback (add a key in .env)"
        ),
        "ai_available": ai.available(),
        "graph_cycles": find_cycles(),
        "graph": GRAPH_SERVICES,
        "detector_alive": bool(detector and detector.is_alive()),
        "thresholds": {"latency_s": config.latency_threshold_s, "error_rate": config.error_rate_threshold},
    }


@app.route("/")
def index():
    return render_template("index.html", state=collect_state())


@app.route("/api/state")
def api_state():
    return jsonify(collect_state())


@app.route("/health")
def health():
    return {"status": "ok", "detector_running": bool(detector and detector.is_alive())}


# ---- remediation actions (sandboxed) ---------------------------------------

@app.route("/action/<name>", methods=["POST"])
def action(name):
    incident_id = request.form.get("incident_id", type=int)
    service = request.form.get("service")  # service-level actions (resume, restart)
    incident = store.get(incident_id) if incident_id else None
    target = incident or ({"service": service} if service else None)
    if not target:
        return redirect(url_for("index"))
    try:
        result = copilot_actions.apply(target, name)
        message = f"Action '{name}': {result}"
        if incident:
            store.add_timeline(incident_id, message)
        print(f"[action] {name} {target['service']}: {result}")
    except copilot_actions.ActionError as exc:
        if incident:
            store.add_timeline(incident_id, f"Action '{name}' failed: {exc}")
        print(f"[action] {name} {target['service']} failed: {exc}")
    anchor = f"#incident-{incident_id}" if incident else "#services"
    return redirect(url_for("index") + anchor)


@app.route("/ack", methods=["POST"])
def ack():
    incident_id = request.form.get("incident_id", type=int)
    if incident_id:
        store.ack(incident_id)
    return redirect(url_for("index") + f"#incident-{incident_id}")


# ---- chaos triggers (demo input) --------------------------------------------

@app.route("/chaos/<kind>", methods=["POST"])
def chaos(kind):
    service = request.form.get("service", "payment-service")
    url = config.payment_service_url if service == "payment-service" else config.order_service_url
    try:
        if kind in ("slow", "errors"):
            requests.post(f"{url}/chaos/{kind}?enabled=true", timeout=5)
        elif kind == "clear":
            requests.post(f"{url}/chaos/clear", timeout=5)
    except requests.RequestException:
        pass
    return redirect(url_for("index"))


# ---- deploy recording (correlation input) ------------------------------------

@app.route("/deploys", methods=["POST"])
def deploys():
    service = request.form.get("service", "payment-service")
    note = request.form.get("note", "")
    correlation.record_deploy(service, note=note)
    return redirect(url_for("index"))


# ---- demo helpers -------------------------------------------------------------

@app.route("/admin/reset", methods=["POST"])
def reset_demo():
    store.clear()
    print("[admin] demo data reset: incidents cleared")
    return redirect(url_for("index"))


def main():
    start_detector()
    app.run(host="0.0.0.0", port=8000, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
