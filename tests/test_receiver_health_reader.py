import json
from datetime import datetime, timedelta, timezone

from sylo.receiver.health import ReceiverHealth, status_path
from sylo.webapp.receiver_health import read_receiver_health


def test_missing_status_file_is_unhealthy(tmp_path):
    status = read_receiver_health(tmp_path)
    assert not status.healthy
    assert "has not reported in yet" in status.reason


def test_malformed_status_file_is_unhealthy(tmp_path):
    (tmp_path / "receiver_status.json").write_text("not json")
    status = read_receiver_health(tmp_path)
    assert not status.healthy
    assert "malformed" in status.reason


def test_running_and_fresh_is_healthy(tmp_path):
    ReceiverHealth(tmp_path).mark_running()
    status = read_receiver_health(tmp_path)
    assert status.healthy
    assert status.reason is None
    assert status.since is None


def test_error_state_is_unhealthy_with_reason(tmp_path):
    ReceiverHealth(tmp_path).mark_failed("[WinError 10013] access forbidden")
    status = read_receiver_health(tmp_path)
    assert not status.healthy
    assert "access forbidden" in status.reason
    assert status.since is not None


def test_stale_heartbeat_is_unhealthy_even_if_last_state_was_running(tmp_path):
    health = ReceiverHealth(tmp_path)
    health.mark_running()
    # Simulate a process that died without a clean stop (killed outright,
    # host crash) by backdating the heartbeat past the staleness threshold.
    path = status_path(tmp_path)
    data = json.loads(path.read_text())
    data["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    path.write_text(json.dumps(data))

    status = read_receiver_health(tmp_path)
    assert not status.healthy
    assert "no update from the receiver" in status.reason
