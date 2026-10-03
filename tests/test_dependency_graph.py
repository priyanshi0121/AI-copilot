from copilot.dependency_graph import (
    are_connected,
    bfs_blast_radius,
    dfs_root_cause_path,
    find_cycles,
    topo_restart_order,
)


def test_root_cause_path_descends_to_deepest_dependency():
    path = dfs_root_cause_path("api-gateway")
    # api-gateway -> order-service -> payment-service -> notification-service
    assert path[0] == "api-gateway"
    assert path[-1] == "notification-service"
    assert "order-service" in path


def test_blast_radius_layers_nearest_first():
    layers = bfs_blast_radius("payment-service")
    # direct dependents first, then theirs
    assert layers[0] == ["order-service"]
    assert layers[1] == ["api-gateway"]
    # inventory-service is NOT affected by payment failure
    flat = [svc for layer in layers for svc in layer]
    assert "inventory-service" not in flat


def test_blast_radius_of_top_level_service_is_empty():
    # nobody depends on api-gateway, so its failure affects nothing else
    assert bfs_blast_radius("api-gateway") == []
    # notification-service is the deepest sink — many services depend on it
    layers = bfs_blast_radius("notification-service")
    assert layers[0] == ["inventory-service", "payment-service"]
    assert layers[1] == ["order-service"]
    assert layers[2] == ["api-gateway"]


def test_cycle_detection_flags_injected_cycle():
    graph = {
        "a": ["b"],
        "b": ["c"],
        "c": ["a"],
        "d": [],
    }
    cycles = find_cycles(graph)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"a", "b", "c"}


def test_no_cycles_in_real_graph():
    assert find_cycles() == []


def test_topo_restart_order_puts_dependencies_first():
    order = topo_restart_order(["order-service", "payment-service", "inventory-service"])
    assert order.index("payment-service") < order.index("order-service")
    assert order.index("inventory-service") < order.index("order-service")


def test_connected_services_in_graph():
    assert are_connected("order-service", "payment-service")
    assert are_connected("order-service", "notification-service")  # through payment
    assert are_connected("payment-service", "auth-service")  # undirected through gateway
    assert are_connected("auth-service", "notification-service")  # transitive via gateway
    assert not are_connected("auth-service", "not-a-service")  # unknown node never connects
