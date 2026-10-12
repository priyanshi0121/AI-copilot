import pytest

from copilot.actions import ActionError, apply, _check_sandbox
from copilot.incidents import IncidentStore


def test_sandbox_rejects_unknown_containers():
    with pytest.raises(ActionError):
        _check_sandbox("some-other-project-db")


def test_sandbox_allows_only_project_services():
    from copilot.actions import ALLOWED_CONTAINERS
    assert ALLOWED_CONTAINERS == {"order-service", "payment-service"}


def test_apply_rejects_unknown_action():
    with pytest.raises(ActionError):
        apply({"service": "payment-service"}, "format-disk")


def test_apply_known_actions_map(monkeypatch):
    from copilot import actions

    called = {}
    monkeypatch.setattr(actions, "restart", lambda svc: f"restarted {svc}")
    assert apply({"service": "payment-service"}, "restart") == "restarted payment-service"
    called["ok"] = True
    assert called["ok"]


def test_store_clear_resets_everything(tmp_path):
    store = IncidentStore(str(tmp_path / "incidents.json"))
    store.create("payment-service", "latency", 2.0, 0.5)
    assert len(store.list()) == 1
    store.clear()
    assert store.list() == []
    # next id restarts cleanly
    fresh = store.create("order-service", "error", 0.5, 0.3)
    assert fresh["id"] == 1


# ---- hosted mode (no Docker socket, e.g. Render) ----------------------------


def test_docker_available_probes_once_then_caches(monkeypatch):
    import sys
    import types

    from copilot import actions

    probes = {"n": 0}

    class FakeClient:
        def ping(self):
            probes["n"] += 1
            raise RuntimeError("no socket")

    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(from_env=lambda: FakeClient()))
    monkeypatch.setattr(actions, "_docker_available", None)

    assert actions.docker_available() is False
    assert actions.docker_available() is False
    assert probes["n"] == 1  # cached after the first probe


def test_docker_actions_refused_without_docker(monkeypatch):
    from copilot import actions

    monkeypatch.setattr(actions, "docker_available", lambda: False)
    for fn in (actions.restart, actions.isolate, actions.resume):
        with pytest.raises(ActionError) as exc:
            fn("order-service")
        assert "Docker socket" in str(exc.value)


def test_rollback_degrades_to_http_clear_without_docker(monkeypatch):
    from copilot import actions

    monkeypatch.setattr(actions, "docker_available", lambda: False)

    posted = {}

    class FakeResp:
        ok = True
        status_code = 200

    def fake_post(url, timeout=None):
        posted["url"] = url
        return FakeResp()

    monkeypatch.setattr(actions.requests, "post", fake_post)
    monkeypatch.setattr(actions, "restart", lambda svc: pytest.fail("restart must not run without Docker"))

    message = actions.rollback("payment-service")

    assert posted["url"].endswith("/chaos/clear")
    assert "chaos flags cleared" in message
    assert "restart skipped" in message


def test_rollback_still_restarts_when_docker_present(monkeypatch):
    from copilot import actions

    monkeypatch.setattr(actions, "docker_available", lambda: True)
    monkeypatch.setattr(actions.requests, "post", lambda url, timeout=None: type("R", (), {"ok": True, "status_code": 200})())
    restarted = {}
    monkeypatch.setattr(actions, "restart", lambda svc: restarted.setdefault("svc", svc))

    message = actions.rollback("order-service")

    assert restarted["svc"] == "order-service"
    assert "restarted" in message
