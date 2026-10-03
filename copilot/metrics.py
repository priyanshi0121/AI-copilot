"""Thin helpers around the Prometheus HTTP API. All functions return None when
there is no data yet (fresh scrape targets, quiet traffic) — callers treat
None as "healthy / unknown", never as an alert."""
import time

import requests

from .config import config


def query(expr: str):
    try:
        resp = requests.get(
            f"{config.prometheus_url}/api/v1/query",
            params={"query": expr},
            timeout=5,
        )
        resp.raise_for_status()
        result = resp.json().get("data", {}).get("result", [])
        if result:
            return float(result[0]["value"][1])
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None
    return None


def avg_latency(histogram_name: str, window: str = "30s"):
    """Mean request latency in seconds over the window."""
    return query(f"rate({histogram_name}_sum[{window}]) / rate({histogram_name}_count[{window}])")


def error_rate(counter_name: str, window: str = "30s"):
    """Fraction of non-200 requests over the window (0..1)."""
    expr = (
        f'sum(rate({counter_name}{{status!="200"}}[{window}])) / '
        f"sum(rate({counter_name}[{window}]))"
    )
    value = query(expr)
    return value if value is not None else 0.0


def request_rate(counter_name: str, window: str = "30s"):
    value = query(f"sum(rate({counter_name}[{window}]))")
    return value if value is not None else 0.0


def service_up(job_name: str):
    """Prometheus scrape target health: 1 = up, 0 = down, None = unknown."""
    return query(f'up{{job="{job_name}"}}')


def latency_series(histogram_name: str, minutes: int = 30, step_s: int = 45, points: int = 40):
    """Recent avg-latency samples for dashboard sparklines. [] when no data."""
    end = time.time()
    start = end - minutes * 60
    expr = f"rate({histogram_name}_sum[1m]) / rate({histogram_name}_count[1m])"
    try:
        resp = requests.get(
            f"{config.prometheus_url}/api/v1/query_range",
            params={"query": expr, "start": start, "end": end, "step": step_s},
            timeout=5,
        )
        resp.raise_for_status()
        result = resp.json().get("data", {}).get("result", [])
        if result:
            values = [float(v[1]) for v in result[0]["values"]]
            if len(values) > points:
                idx = [round(i * (len(values) - 1) / (points - 1)) for i in range(points)]
                values = [values[i] for i in idx]
            return values
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return []
    return []


# the services the copilot watches, mapped to their metric names
MONITORED_SERVICES = [
    {
        "name": "order-service",
        "job": "order-service",
        "histogram": "order_request_latency_seconds",
        "counter": "order_requests_total",
        "url_key": "order_service_url",
    },
    {
        "name": "payment-service",
        "job": "payment-service",
        "histogram": "payment_request_latency_seconds",
        "counter": "payment_requests_total",
        "url_key": "payment_service_url",
    },
]
