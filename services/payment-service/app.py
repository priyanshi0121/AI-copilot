import os
import random
import time

from flask import Flask, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

app = Flask(__name__)

REQUEST_COUNT = Counter("payment_requests_total", "Total requests", ["status"])
REQUEST_LATENCY = Histogram("payment_request_latency_seconds", "Request latency")

# env var kept for chaos-at-container-start; runtime toggles use /chaos/* endpoints
SLOW_MODE = os.environ.get("SLOW_MODE", "false") == "true"

chaos = {"slow": SLOW_MODE, "errors": False}


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "payment-service", "chaos": chaos})


@app.route("/pay", methods=["GET", "POST"])
def pay():
    start = time.time()
    status = "200"
    try:
        delay = random.uniform(0.1, 0.2)
        if chaos["slow"]:
            delay += 2.0  # artificial slowness for chaos testing
        time.sleep(delay)

        if chaos["errors"]:
            status = "500"

        body = {"message": "Payment processed", "service": "payment-service", "status": status}
        if status != "200":
            return jsonify(body), int(status)
        return jsonify(body)
    finally:
        REQUEST_COUNT.labels(status=status).inc()
        REQUEST_LATENCY.observe(time.time() - start)


@app.route("/chaos/slow", methods=["POST"])
def chaos_slow():
    chaos["slow"] = request.args.get("enabled", "true") == "true"
    return jsonify({"service": "payment-service", "chaos": chaos})


@app.route("/chaos/errors", methods=["POST"])
def chaos_errors():
    chaos["errors"] = request.args.get("enabled", "true") == "true"
    return jsonify({"service": "payment-service", "chaos": chaos})


@app.route("/chaos/clear", methods=["POST"])
def chaos_clear():
    chaos["slow"] = False
    chaos["errors"] = False
    return jsonify({"service": "payment-service", "chaos": chaos})


@app.route("/chaos/status")
def chaos_status():
    return jsonify({"service": "payment-service", "chaos": chaos})


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5002)), threaded=True)
