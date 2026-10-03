from copilot.prioritizer import prioritize, priority_score


def incident(iid, value, kind="latency"):
    return {"id": iid, "service": f"svc-{iid}", "kind": kind, "cost_estimate": {"projected_24h_usd": value}}


def test_highest_ratio_first():
    plan = prioritize([incident(1, 100.0), incident(2, 900.0)], capacity_min=60)
    # svc-2: 900/30 (error, 30min) = $30/min; svc-1: 100/15 = $6.67/min
    assert plan["plan"][0]["incident_id"] == 2
    assert plan["plan"][0]["take"] == "full"


def test_fractional_take_when_window_is_tight():
    plan = prioritize([incident(1, 100.0)], capacity_min=5)
    item = plan["plan"][0]
    assert item["take"].startswith("partial")
    # 5 of 15 minutes = 1/3 of the value recovered
    assert plan["covered_usd"] == round(100.0 / 3, 2)


def test_deferred_beyond_capacity():
    plan = prioritize([incident(1, 100.0), incident(2, 50.0)], capacity_min=15)
    # latency items: 15 min each; only one fits in a 15-min window
    assert len(plan["plan"]) == 1
    assert plan["plan"][0]["take"] == "full"
    assert [i["incident_id"] for i in plan["deferred"]] == [2]
    assert plan["covered_usd"] < plan["total_at_risk_usd"]


def test_priority_score_is_value_per_fix_minute():
    assert priority_score(incident(1, 300.0, "error")) == 10.0
    assert priority_score({}) == 0.0
