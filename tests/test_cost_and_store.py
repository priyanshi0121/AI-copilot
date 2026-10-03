from copilot.cost import estimate_error_cost, estimate_latency_cost
from copilot.incidents import IncidentStore


def test_latency_cost_scales_with_slowness(tmp_path):
    mild = estimate_latency_cost(0.4)
    severe = estimate_latency_cost(2.2)
    assert severe["per_hour_usd"] > mild["per_hour_usd"] > 0
    assert severe["projected_24h_usd"] == round(severe["per_hour_usd"] * 24, 2)


def test_latency_at_baseline_costs_nothing():
    assert estimate_latency_cost(0.2)["per_hour_usd"] == 0.0


def test_error_cost_is_revenue_at_risk():
    result = estimate_error_cost(0.5, requests_per_min=10.0)
    # 0.5 * 10 * 60 = 300 failed orders/hr * $42 = $12,600/hr
    assert result["per_hour_usd"] == 12600.0


def test_down_incident_costs_full_revenue(tmp_path=None):
    from copilot.cost import estimate_cost
    result = estimate_cost({"kind": "down", "detected_value": 0.0}, requests_per_min=10.0)
    # fully down = 100% of transactions lost
    assert result["per_hour_usd"] == estimate_error_cost(1.0, 10.0)["per_hour_usd"]


def test_incident_store_roundtrip(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.json"))
    inc = store.create("payment-service", "latency", 2.2, 0.5)
    assert inc["id"] == 1
    store.update(inc["id"], root_cause="bad deploy", confidence=88)
    store.add_timeline(inc["id"], "enriched")
    store.resolve(inc["id"], "rollback executed")

    reloaded = IncidentStore(str(tmp_path / "incidents.json"))
    got = reloaded.get(1)
    assert got["status"] == "resolved"
    assert got["root_cause"] == "bad deploy"
    assert got["confidence"] == 88
    assert len(got["timeline"]) == 3  # detected + enriched + resolved
    assert reloaded.find_open("payment-service", "latency") is None


def test_incident_ids_increment(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.json"))
    a = store.create("order-service", "error", 0.4, 0.3)
    b = store.create("order-service", "latency", 1.1, 0.5)
    assert b["id"] == a["id"] + 1
