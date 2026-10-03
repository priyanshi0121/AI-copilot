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
