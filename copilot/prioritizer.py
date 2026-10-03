"""Incident prioritization as the Greedy Method / Fractional Knapsack.

Each open incident is an item: value = estimated cost impact ($), weight =
estimated fix time (minutes). Given one engineer's time window, greedily pick
the highest cost-savings-per-minute incidents first; the last item that does
not fully fit is taken fractionally (partial fix ≈ partial saving) — which is
the fractional-knapsack twist over plain greedy."""
from .config import config


def prioritize(incidents: list, capacity_min: int = None) -> dict:
    capacity_min = capacity_min or config.engineer_window_min
    items = []
    for incident in incidents:
        cost = incident.get("cost_estimate") or {}
        value = float(cost.get("projected_24h_usd", 0.0) or 0.0)
        weight = int(config.est_fix_minutes.get(incident.get("kind"), 15))
        ratio = value / weight if weight else 0.0
        items.append(
            {
                "incident_id": incident["id"],
                "service": incident["service"],
                "kind": incident["kind"],
                "value_usd": round(value, 2),
                "weight_min": weight,
                "ratio_usd_per_min": round(ratio, 2),
            }
        )

    items.sort(key=lambda item: item["ratio_usd_per_min"], reverse=True)

    plan, remaining, covered = [], capacity_min, 0.0
    for item in items:
        if remaining <= 0:
            item["take"] = "deferred"
            continue
        if item["weight_min"] <= remaining:
            item["take"] = "full"
            remaining -= item["weight_min"]
            covered += item["value_usd"]
        else:
            fraction = remaining / item["weight_min"]
            item["take"] = f"partial ({fraction:.0%} — mitigate now, finish after the window)"
            covered += item["value_usd"] * fraction
            remaining = 0
        plan.append(item)

    deferred = [item for item in items if item.get("take") == "deferred"]
    return {
        "capacity_min": capacity_min,
        "plan": plan,
        "covered_usd": round(covered, 2),
        "total_at_risk_usd": round(sum(i["value_usd"] for i in items), 2),
        "deferred": deferred,
    }


def priority_score(incident: dict) -> float:
    """Standalone score for a single incident: $ of impact per fix-minute."""
    cost = incident.get("cost_estimate") or {}
    value = float(cost.get("projected_24h_usd", 0.0) or 0.0)
    weight = int(config.est_fix_minutes.get(incident.get("kind"), 15))
    return round(value / weight, 2) if weight else 0.0
