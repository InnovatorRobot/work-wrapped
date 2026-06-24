def test_team_optin_and_aggregate(demo_client):
    # Opt in
    r = demo_client.post("/api/team-comparison", json={"include": True})
    assert r.status_code == 200
    assert r.json()["include"] is True

    # Aggregate is names-free and well-shaped
    team = demo_client.get("/api/team").json()
    assert "participant_count" in team
    assert set(team["totals"].keys()) == {"jira", "gerrit", "confluence", "slack"}
    assert "average" in team
    # No per-user names exposed
    assert "users" not in team or not team.get("users")

    # Opt out
    r = demo_client.post("/api/team-comparison", json={"include": False})
    assert r.json()["include"] is False


def test_team_page_renders(demo_client):
    assert demo_client.get("/team").status_code == 200
    assert demo_client.get("/api/team/export/csv").status_code == 200
