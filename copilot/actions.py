"""Sandboxed remediation actions via the Docker SDK.

Sandbox rules:
- Only this project's containers may be touched (hard-coded allow-list).
- `rollback` clears the service's chaos/runtime flags over HTTP, then restarts
  the container to reset process state.
- `isolate` stops the container to contain blast radius (demo of containment).
- `resume` starts a stopped/isolated container again.
"""
import requests

from .config import config

ALLOWED_CONTAINERS = {"order-service", "payment-service"}


class ActionError(Exception):
    pass


def _service_url(service: str) -> str:
    urls = {
        "order-service": config.order_service_url,
        "payment-service": config.payment_service_url,
    }
    if service not in urls:
        raise ActionError(f"Sandboxed: '{service}' is not an allowed target {sorted(ALLOWED_CONTAINERS)}")
    return urls[service]


def _docker_client():
    try:
        import docker

        return docker.from_env()
    except Exception as exc:
        raise ActionError(f"Docker unavailable ({exc}) — is Docker Desktop running?") from exc


def _check_sandbox(service: str):
    if service not in ALLOWED_CONTAINERS:
        raise ActionError(f"Sandboxed: '{service}' is not an allowed target {sorted(ALLOWED_CONTAINERS)}")


def restart(service: str) -> str:
    _check_sandbox(service)
    client = _docker_client()
    container = client.containers.get(service)
    container.restart(timeout=20)
    return f"Restarted container '{service}'"


def rollback(service: str) -> str:
    """Revert runtime config (chaos flags) then restart to reset process state."""
    _check_sandbox(service)
    notes = []
    try:
        resp = requests.post(f"{_service_url(service)}/chaos/clear", timeout=5)
        notes.append(f"runtime chaos flags cleared ({resp.status_code})" if resp.ok else "chaos-clear endpoint non-200")
    except requests.RequestException:
        notes.append("chaos-clear endpoint unreachable (flags reset by restart anyway)")
    restart(service)
    notes.append(f"container '{service}' restarted")
    return "Rollback: " + "; ".join(notes)


def isolate(service: str) -> str:
    _check_sandbox(service)
    client = _docker_client()
    container = client.containers.get(service)
    container.stop(timeout=20)
    return f"Isolated (stopped) container '{service}' to contain blast radius"


def resume(service: str) -> str:
    _check_sandbox(service)
    client = _docker_client()
    container = client.containers.get(service)
    container.start()
    return f"Resumed (started) container '{service}'"


def apply(incident: dict, action: str) -> str:
    actions = {"restart": restart, "rollback": rollback, "isolate": isolate, "resume": resume}
    if action not in actions:
        raise ActionError(f"Unknown action '{action}' — allowed: {sorted(actions)}")
    return actions[action](incident["service"])
