from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.worker import tick

client = TestClient(app)


def test_liveness():
    assert client.get("/health/live").json() == {"status": "ok"}


def test_readiness_requires_migrated_database():
    with patch("app.main.ready", side_effect=RuntimeError("offline")):
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
    with patch("app.main.ready"):
        assert client.get("/health/ready").status_code == 200


def test_no_fixtures_in_status():
    data = client.get("/api/status").json()
    assert data["generation"] == {"status": "unavailable", "value_mw": None}
    assert data["weather"] == {"status": "unavailable", "sites": []}


def test_worker_commits_heartbeat():
    with patch("app.worker.connect") as connect:
        tick()
        query = connect.return_value.__enter__.return_value.execute.call_args.args[0]
        assert "ON CONFLICT" in query


def test_worker_health_rejects_missing_heartbeat():
    import pytest
    from app.worker_health import check

    with patch("app.worker_health.connect") as connect:
        connection = connect.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = (0,)
        with pytest.raises(RuntimeError, match="stale"):
            check()
        connection.execute.return_value.fetchone.return_value = (1,)
        check()
