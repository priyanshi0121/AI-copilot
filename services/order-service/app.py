import os
import random
import time

import requests
from flask import Flask, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

app = Flask(__name__)

REQUEST_COUNT = Counter("order_requests_total", "Total requests", ["status"])
REQUEST_LATENCY = Histogram("order_request_latency_seconds", "Request latency")

# order-service depends on payment-service: a payment failure propagates upstream
PAYMENT_URL = os.environ.get("PAYMENT_URL", "http://payment-service:5002/pay")
SLOW_MODE = os.environ.get("SLOW_MODE", "false") == "true"

# runtime chaos flags (also settable via env at container start)
chaos = {"slow": SLOW_MODE, "errors": False}


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "order-service", "chaos": chaos})


@app.route("/order")
def order():
    start = time.time()
    status = "200"
    try:
        delay = random.uniform(0.1, 0.3)
        if chaos["slow"]:
            delay += 1.5
        time.sleep(delay)

        try:
            resp = requests.post(PAYMENT_URL, timeout=10)
            if resp.status_code != 200:
                status = "502"
        except requests.RequestException:
            status = "502"

        if chaos["errors"]:
            status = "500"

        body = {"message": "Order placed", "service": "order-service", "status": status}
        if status != "200":
            return jsonify(body), int(status)
        return jsonify(body)
    finally:
        REQUEST_COUNT.labels(status=status).inc()
        REQUEST_LATENCY.observe(time.time() - start)


@app.route("/chaos/slow", methods=["POST"])
def chaos_slow():
    chaos["slow"] = request.args.get("enabled", "true") == "true"
    return jsonify({"service": "order-service", "chaos": chaos})


@app.route("/chaos/errors", methods=["POST"])
def chaos_errors():
    chaos["errors"] = request.args.get("enabled", "true") == "true"
    return jsonify({"service": "order-service", "chaos": chaos})


@app.route("/chaos/clear", methods=["POST"])
def chaos_clear():
    chaos["slow"] = False
    chaos["errors"] = False
    return jsonify({"service": "order-service", "chaos": chaos})


@app.route("/chaos/status")
def chaos_status():
    return jsonify({"service": "order-service", "chaos": chaos})


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), threaded=True)
