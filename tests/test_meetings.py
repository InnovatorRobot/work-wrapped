def test_meeting_crud_and_carry_forward(demo_client):
    # Create a meeting (no seed to keep it deterministic)
    r = demo_client.post(
        "/api/meetings", json={"title": "June 1:1", "date": "2026-06-20", "seed": False}
    )
    assert r.status_code == 200
    m1 = r.json()["meeting"]
    assert m1["status"] == "scheduled"

    # Add one open + one done action
    r = demo_client.post(
        "/api/meetings/" + m1["id"],
        json={
            "notes": "Discussed roadmap.",
            "action_items": [
                {"text": "Draft plan", "owner": "me", "status": "open"},
                {"text": "Share doc", "owner": "manager", "status": "done"},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["meeting"]["notes"] == "Discussed roadmap."

    # New meeting carries forward only the OPEN action
    r = demo_client.post(
        "/api/meetings", json={"title": "July 1:1", "date": "2026-07-20", "seed": False}
    )
    m2 = r.json()["meeting"]
    carried = m2["action_items"]
    assert len(carried) == 1
    assert carried[0]["text"] == "Draft plan"
    assert carried[0]["carried_over"] is True

    # History newest first
    meetings = demo_client.get("/api/meetings").json()["meetings"]
    assert meetings[0]["date"] >= meetings[-1]["date"]

    # Delete
    assert demo_client.request("DELETE", "/api/meetings/" + m2["id"]).status_code == 200


def test_meeting_empty_payload_ok(demo_client):
    r = demo_client.post("/api/meetings", json={"seed": False})
    assert r.status_code == 200
    assert r.json()["meeting"]["title"]
