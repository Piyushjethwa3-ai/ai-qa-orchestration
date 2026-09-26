"""
Baseline test for GET /employees/me.

This covers the happy path only. Day 1/Day 2 exercises can add cases for
a missing header and an unknown employee id (BR01), which should both
return 400.
"""


def test_get_my_profile_returns_known_employee(client):
    response = client.get("/employees/me", headers={"X-Demo-Employee-ID": "EMP001"})

    assert response.status_code == 200
    body = response.json()
    assert body["employee_id"] == "EMP001"
    assert body["full_name"] == "Dana Whitfield"
