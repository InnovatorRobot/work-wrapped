def test_csrf_blocks_cross_origin_post(demo_client):
    r = demo_client.post(
        "/api/team-comparison",
        json={"include": True},
        headers={"origin": "https://evil.example.com"},
    )
    assert r.status_code == 403


def test_same_origin_post_allowed(demo_client):
    # TestClient default base is http://testserver; matching origin is allowed.
    r = demo_client.post(
        "/api/team-comparison",
        json={"include": True},
        headers={"origin": "http://testserver"},
    )
    assert r.status_code == 200
