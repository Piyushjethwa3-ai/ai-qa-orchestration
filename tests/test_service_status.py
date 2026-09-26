"""
Baseline tests for GET /health and GET /services/vpn/status.

Day 1/Day 2 exercises can add cases such as asserting on the full set of
allowed status values, or checking the response when the status file is
in a "degraded" or "outage" state.
"""


def test_health_check_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_vpn_status_has_defined_status_and_update_time(client):
    response = client.get("/services/vpn/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("operational", "degraded", "outage")
    assert "updated_at" in body
