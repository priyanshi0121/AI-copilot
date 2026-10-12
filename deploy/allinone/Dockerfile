# All-in-one bundle for single-service hosts (Render, Railway, Fly, ...).
#
# Runs Prometheus + order-service + payment-service + loadgen + the copilot
# inside ONE container so no inter-service networking is needed and a single
# public HTTP port is enough. Used by render.yaml.
#
# The local Docker Compose stack (docker-compose.yml) remains the full-fidelity
# deployment: 6 containers, plus Docker-backed restart/isolate/resume actions
# that cannot work here because there is no Docker socket.

# --- stage 1: take the static Prometheus binary from the official image ---
FROM prom/prometheus:latest AS prometheus

# --- stage 2: the bundle ---
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY --from=prometheus /bin/prometheus /usr/local/bin/prometheus

# the root requirements are a superset of the services' needs
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt supervisor

COPY copilot ./copilot
COPY dashboard ./dashboard
COPY services/order-service ./services/order-service
COPY services/payment-service ./services/payment-service

COPY deploy/allinone/prometheus.yml /etc/prometheus/prometheus.yml
COPY deploy/allinone/loadgen.py ./loadgen.py
COPY deploy/allinone/supervisord.conf /etc/supervisord.conf

# Everything talks over localhost. The copilot's Prometheus URL carries the
# /prometheus route prefix, which is how the proxy in dashboard/app.py and the
# PromQL queries in copilot/metrics.py both reach it.
ENV DATA_DIR=/tmp/aiops-data \
    PROMETHEUS_URL=http://127.0.0.1:9090/prometheus \
    ORDER_SERVICE_URL=http://127.0.0.1:5001 \
    PAYMENT_SERVICE_URL=http://127.0.0.1:5002 \
    CHECK_INTERVAL_S=10

# documentation only — the host injects the real listen port via $PORT
EXPOSE 8000

CMD ["supervisord", "-c", "/etc/supervisord.conf"]
