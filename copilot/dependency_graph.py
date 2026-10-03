"""Service dependency graph and the classic algorithms the copilot runs on it.

Graph mirrors the guide's architecture:

    api-gateway
     |-- auth-service
     +-- order-service
          |-- payment-service --> notification-service
          +-- inventory-service --> notification-service

Edges point from a service to the things it depends on.
"""
from collections import deque

SERVICE_DEPENDENCIES = {
    "api-gateway": ["auth-service", "order-service"],
    "order-service": ["payment-service", "inventory-service"],
    "payment-service": ["notification-service"],
    "inventory-service": ["notification-service"],
    "auth-service": [],
    "notification-service": [],
}

MONITORED_SERVICES = ["order-service", "payment-service"]


def dependencies_of(service: str) -> list:
    return list(SERVICE_DEPENDENCIES.get(service, []))


def dependents_of(service: str) -> list:
    """Reverse edges: who calls this service (i.e. who suffers when it fails)."""
    return [svc for svc, deps in SERVICE_DEPENDENCIES.items() if service in deps]


def dfs_root_cause_path(service: str, graph=None, path=None) -> list:
    """DFS: follow one causal chain as deep as it goes.

    A symptom on `service` may really be caused by something it depends on,
    so we descend into dependencies and return the deepest chain
    [symptom, ..., probable root cause].
    """
    graph = graph or SERVICE_DEPENDENCIES
    path = list(path or []) + [service]
    deps = [d for d in graph.get(service, []) if d not in path]  # cycle-safe
    if not deps:
        return path
    best = max((dfs_root_cause_path(d, graph, path) for d in deps), key=len)
    return best


def bfs_blast_radius(service: str, graph=None) -> list:
    """BFS over reverse edges, layer by layer: which services are affected
    if `service` fails. Layers[0] = direct dependents, layers[1] = theirs, etc."""
    graph = graph or SERVICE_DEPENDENCIES
    reverse = {}
    for svc, deps in graph.items():
        for dep in deps:
            reverse.setdefault(dep, []).append(svc)

    layers, seen, frontier = [], {service}, [service]
    while frontier:
        nxt = []
        for node in frontier:
            for parent in reverse.get(node, []):
                if parent not in seen:
                    seen.add(parent)
                    nxt.append(parent)
        if nxt:
            layers.append(sorted(nxt))
        frontier = nxt
    return layers


def find_cycles(graph=None) -> list:
    """DFS cycle detection (white/grey/black colouring). Circular dependencies
    between services are a design bug worth flagging before they bite."""
    graph = graph or SERVICE_DEPENDENCIES
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {node: WHITE for node in graph}
    cycles = []

    def visit(node, stack):
        colour[node] = GREY
        stack.append(node)
        for dep in graph.get(node, []):
            if dep not in colour:
                continue
            if colour[dep] == GREY:
                idx = stack.index(dep)
                cycles.append(stack[idx:] + [dep])
            elif colour[dep] == WHITE:
                visit(dep, stack)
        stack.pop()
        colour[node] = BLACK

    for node in graph:
        if colour[node] == WHITE:
            visit(node, [])
    return cycles


def topo_restart_order(services: list, graph=None) -> list:
    """Safe restart/rollback order for a set of services: dependencies come
    back up before the services that depend on them (DFS post-order)."""
    graph = graph or SERVICE_DEPENDENCIES
    wanted = set(services)
    order, visited, in_progress = [], set(), set()

    def visit(node):
        if node in visited or node in in_progress:
            return
        in_progress.add(node)
        for dep in graph.get(node, []):
            if dep in wanted:
                visit(dep)
        in_progress.discard(node)
        visited.add(node)
        order.append(node)

    for svc in sorted(wanted):
        visit(svc)
    return order


def are_connected(a: str, b: str, graph=None) -> bool:
    """Undirected connectivity (BFS) — used for alert clustering: two alerts on
    connected services are probably one incident, not two."""
    if a == b:
        return True
    graph = graph or SERVICE_DEPENDENCIES
    undirected = {}
    for svc, deps in graph.items():
        undirected.setdefault(svc, set()).update(deps)
        for dep in deps:
            undirected.setdefault(dep, set()).add(svc)
    seen, queue = {a}, deque([a])
    while queue:
        node = queue.popleft()
        for nbr in undirected.get(node, []):
            if nbr == b:
                return True
            if nbr not in seen:
                seen.add(nbr)
                queue.append(nbr)
    return False
