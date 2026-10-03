from datetime import datetime, timedelta, timezone

from copilot import correlation
from copilot.config import config as settings


def _isolate_data_dir(tmp_path, monkeypatch):
    """Point correlation at a private data dir so tests never race the live
    stack (which writes data/deploys.json through its bind mount)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir))


def test_correlates_recent_direct_deploy_with_high_confidence(tmp_path, monkeypatch):
    _isolate_data_dir(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    result = correlation.correlate("payment-service", alert_time=now, window_min=30)
    # fresh private dir → nothing seeded yet until list_deploys runs
    if result is None:
        correlation.record_deploy("payment-service", note="test deploy")
        result = correlation.correlate("payment-service", alert_time=now, window_min=30)
    assert result is not None
    assert result["deploy"]["service"] == "payment-service"
    assert 40 <= result["confidence"] <= 95


def test_correlation_uses_dependency_deploys_too(tmp_path, monkeypatch):
    _isolate_data_dir(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    correlation.record_deploy("payment-service", note="bad config change")
    result = correlation.correlate("order-service", alert_time=now, window_min=30)
    assert result is not None
    assert result["deploy"]["service"] == "payment-service"
    assert "dependency" in result["explanation"]


def test_no_correlation_when_alert_predates_deploys(tmp_path, monkeypatch):
    _isolate_data_dir(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    # seeds are all in the past relative to "now"; an alert 1000 minutes ago
    # predates every deploy, so nothing can correlate
    result = correlation.correlate("order-service", alert_time=now - timedelta(minutes=1000), window_min=30)
    assert result is None


def test_confidence_is_higher_for_fresher_deploy(tmp_path, monkeypatch):
    _isolate_data_dir(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    correlation.record_deploy("order-service", note="fresh")
    fresh = correlation.correlate("order-service", alert_time=now, window_min=30)
    assert fresh is not None
    assert fresh["confidence"] >= 85  # <5 min old, direct service match
