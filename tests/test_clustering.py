from copilot.clustering import cluster_incidents


def make(iid, service, status="open", started_at="2026-09-26T10:00:00+00:00"):
    return {
        "id": iid,
        "service": service,
        "kind": "latency",
        "status": status,
        "started_at": started_at,
        "priority_score": 1.0,
    }


def test_connected_alerts_within_window_cluster_together():
    clusters = cluster_incidents([make(1, "order-service"), make(2, "payment-service")])
    assert len(clusters) == 1
    assert clusters[0]["size"] == 2
    assert set(clusters[0]["services"]) == {"order-service", "payment-service"}


def test_disconnected_alerts_stay_separate():
    # auth-service has no graph path to "unknown-service" (not in the graph)
    clusters = cluster_incidents([make(1, "auth-service"), make(2, "not-a-service")])
    assert len(clusters) == 2


def test_time_gap_beyond_window_prevents_clustering():
    far = make(2, "payment-service", started_at="2026-09-26T10:30:00+00:00")
    clusters = cluster_incidents([make(1, "order-service"), far])
    assert len(clusters) == 2


def test_resolved_incidents_are_ignored():
    clusters = cluster_incidents([make(1, "order-service", status="resolved"), make(2, "payment-service")])
    assert len(clusters) == 1
    assert clusters[0]["incident_ids"] == [2]
