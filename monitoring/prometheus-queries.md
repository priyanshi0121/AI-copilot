# Prometheus Queries — Demo Reference

Open **http://localhost:9090** → paste a query in the top box → click **Graph** (not Table).

---

## 1. Average latency (the main one — what the copilot runs every 10s)

```
rate(payment_request_latency_seconds_sum[30s]) / rate(payment_request_latency_seconds_count[30s])
```

**Say:** total time spent on requests ÷ number of requests, over a 30-second window = average latency.

## 2. Error rate (fraction of failed requests)

```
sum(rate(payment_requests_total{status!="200"}[30s])) / sum(rate(payment_requests_total[30s]))
```

**Say:** inject errors from the dashboard and watch it jump from 0 to 1 — the same signal that opens an "error" incident.

## 3. p95 latency (95th percentile — the SRE standard)

```
histogram_quantile(0.95, sum by (le) (rate(payment_request_latency_seconds_bucket[30s])))
```

**Say:** the average can hide slow outliers; p95 means 95% of requests are faster than this. Works because the services use Histogram metrics.

## 4. Service health (what powers "down" detection)

```
up{job="payment-service"}
```

**Say:** 1 = up, 0 = down. A failed scrape is how the copilot detects a stopped service.

## 5. Order-service latency (add as a second query to compare both services)

```
rate(order_request_latency_seconds_sum[30s]) / rate(order_request_latency_seconds_count[30s])
```

**Say:** inject slowness and BOTH lines jump — order-service really calls payment-service. The dependency graph, visible in live data.

---

## Bonus queries

```
# request rate (traffic per second)
sum(rate(payment_requests_total[30s]))

# total requests since container start
payment_requests_total
```

---

## Where these queries live in the project (if asked "where did you get them?")

- **`copilot/metrics.py`** — the detector builds the same queries in Python (`avg_latency`, `error_rate`, `service_up`)
- **`monitoring/grafana/dashboards/aiops-overview.json`** — the Grafana panels embed them (open a panel → Edit → see the query)
- **`monitoring/prometheus.yml`** — defines *what* is scraped (the `/metrics` endpoints, every 5s)
- **Prometheus UI history** — the query box keeps recent queries (dropdown arrow) for the current browser session
