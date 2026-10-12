"""Sandboxed remediation actions via the Docker SDK.

Sandbox rules:
- Only this project's containers may be touched (hard-coded allow-list).
- `rollback` clears the service's chaos/runtime flags over HTTP, then restarts
  the container to reset process state.
- `isolate` stops the container to contain blast radius (demo of containment).
- `resume` starts a stopped/isolated container again.

Hosted mode: a container runtime is not always reachable (for example on Render,
where no Docker socket exists). Actions that genuinely need the Docker daemon
are refused with a clear message, and `rollback` degrades to the HTTP
chaos-clear it can still perform on its own.
"""
import threading

import requests

from .config import config

ALLOWED_CONTAINERS = {"order-service", "payment-service"}

HOSTED_HINT = (
    "needs a Docker socket — available in local Docker mode (docker compose up). "
    "In hosted mode the copilot can still clear runtime flags over HTTP."
)

_docker_available = None
_docker_lock = threading.Lock()


class ActionError(Exception):
    pass


def docker_available() -> bool:
    """Whether a Docker daemon is reachable. Probed once, then cached."""
    global _docker_available
    with _docker_lock:
        if _docker_available is None:
            try:
                import docker

                docker.from_env().ping()
                _docker_available = True
            except Exception:
                _docker_available = False
        return _docker_available


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


def _require_docker(action_label: str):
    if not docker_available():
        raise ActionError(f"{action_label} {HOSTED_HINT}")


def _clear_chaos(service: str) -> str:
    """Best-effort HTTP reset of a service's runtime chaos flags."""
    try:
        resp = requests.post(f"{_service_url(service)}/chaos/clear", timeout=5)
        if resp.ok:
            return f"runtime chaos flags cleared ({resp.status_code})"
        return "chaos-clear endpoint non-200"
    except requests.RequestException:
        return "chaos-clear endpoint unreachable (flags reset by restart anyway)"


def restart(service: str) -> str:
    _check_sandbox(service)
    _require_docker("Restart")
    client = _docker_client()
    container = client.containers.get(service)
    container.restart(timeout=20)
    return f"Restarted container '{service}'"


def rollback(service: str) -> str:
    """Revert runtime config (chaos flags) and reset process state if possible."""
    _check_sandbox(service)
    notes = [_clear_chaos(service)]
    if docker_available():
        restart(service)
        notes.append(f"container '{service}' restarted")
    else:
        notes.append("container restart skipped — " + HOSTED_HINT)
    return "Rollback: " + "; ".join(notes)


def isolate(service: str) -> str:
    _check_sandbox(service)
    _require_docker("Isolate")
    client = _docker_client()
    container = client.containers.get(service)
    container.stop(timeout=20)
    return f"Isolated (stopped) container '{service}' to contain blast radius"


def resume(service: str) -> str:
    _check_sandbox(service)
    _require_docker("Resume")
    client = _docker_client()
    container = client.containers.get(service)
    container.start()
    return f"Resumed (started) container '{service}'"


def apply(incident: dict, action: str) -> str:
    actions = {"restart": restart, "rollback": rollback, "isolate": isolate, "resume": resume}
    if action not in actions:
        raise ActionError(f"Unknown action '{action}' — allowed: {sorted(actions)}")
    return actions[action](incident["service"])
