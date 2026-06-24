def test_objective_crud_with_evidence(demo_client):
    # Create with evidence (one invalid empty-label entry should be dropped)
    r = demo_client.post(
        "/api/objectives",
        json={
            "title": "Improve reviews",
            "status": "in_progress",
            "evidence": [
                {"label": "Gerrit changes", "value": 42, "source": "gerrit"},
                {"label": "", "value": 5},
            ],
        },
    )
    assert r.status_code == 200
    obj = r.json()["objective"]
    assert len(obj["evidence"]) == 1
    assert obj["evidence"][0]["label"] == "Gerrit changes"
    oid = obj["id"]

    # List
    items = demo_client.get("/api/objectives").json()["objectives"]
    assert any(o["id"] == oid for o in items)

    # Update
    r = demo_client.post(
        "/api/objectives/" + oid, json={"title": "Improve reviews", "status": "done"}
    )
    assert r.status_code == 200
    assert r.json()["objective"]["status"] == "done"

    # Delete
    assert demo_client.request("DELETE", "/api/objectives/" + oid).status_code == 200
    items = demo_client.get("/api/objectives").json()["objectives"]
    assert not any(o["id"] == oid for o in items)


def test_objective_requires_title(demo_client):
    r = demo_client.post("/api/objectives", json={"title": "   "})
    assert r.status_code == 400
