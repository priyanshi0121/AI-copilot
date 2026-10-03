"""Cost-aware layer (FinOps crossover): attach an estimated financial impact
to every anomaly. Deliberately simple, documented models — the point is to
connect operational signals to dollars, not to replace a cloud bill."""
from .config import config


def estimate_latency_cost(observed_s: float) -> dict:
    """Slow responses hold workers (and their CPU/memory) longer, so sustained
    slowness behaves like accidental over-provisioning. Model the extra cost as
    the extra CPU-hours the ratio implies."""
    baseline = config.baseline_latency_s
    ratio = observed_s / baseline if observed_s and baseline else 1.0
    extra_ratio = max(ratio - 1.0, 0.0)
    extra_vcpu = extra_ratio * config.cpu_per_replica * config.replicas
    per_hour = round(extra_vcpu * config.vcpu_hour_rate, 2)
    return {
        "per_hour_usd": per_hour,
        "projected_24h_usd": round(per_hour * 24, 2),
        "assumptions": (
            f"latency {observed_s:.2f}s vs {baseline:.2f}s baseline → {ratio:.1f}x worker occupancy; "
            f"{config.replicas} replica(s) @ {config.cpu_per_replica} vCPU; ${config.vcpu_hour_rate}/vCPU-hr"
        ),
    }


def estimate_error_cost(error_rate: float, requests_per_min: float) -> dict:
    """Errors are failed business transactions: estimate revenue-at-risk as
    failed orders × average order value."""
    failed_per_hour = error_rate * requests_per_min * 60
    per_hour = round(failed_per_hour * config.avg_order_value, 2)
    return {
        "per_hour_usd": per_hour,
        "projected_24h_usd": round(per_hour * 24, 2),
        "assumptions": (
            f"{error_rate:.0%} of ~{requests_per_min:.1f} pay req/min failing → "
            f"{failed_per_hour:.0f} lost orders/hr @ ${config.avg_order_value:.0f} avg order"
        ),
    }


def estimate_cost(incident: dict, requests_per_min: float = 0.0) -> dict:
    if incident["kind"] == "latency":
        return estimate_latency_cost(incident["detected_value"])
    if incident["kind"] == "down":
        # service unavailable = every transaction it serves is lost
        return estimate_error_cost(1.0, requests_per_min)
    return estimate_error_cost(incident["detected_value"], requests_per_min)
