import uuid


def test_unauthenticated_redirects(client):
    r = client.get("/api/personal", follow_redirects=False)
    assert r.status_code == 307
    assert "/login" in r.headers.get("location", "")


def test_demo_login_grants_access(demo_client):
    r = demo_client.get("/api/personal")
    assert r.status_code == 200


def test_signup_login_logout(client):
    email = "user_{}@example.com".format(uuid.uuid4().hex[:8])
    r = client.post(
        "/signup",
        data={"email": email, "password": "secret123", "password2": "secret123", "name": "T"},
        follow_redirects=False,
    )
    assert r.status_code == 303  # established session, redirect to dashboard
    assert client.get("/api/personal").status_code == 200

    client.get("/logout", follow_redirects=False)
    assert client.get("/api/personal", follow_redirects=False).status_code == 307

    r = client.post(
        "/login", data={"email": email, "password": "secret123"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert client.get("/api/personal").status_code == 200


def test_signup_password_mismatch(client):
    email = "user_{}@example.com".format(uuid.uuid4().hex[:8])
    r = client.post(
        "/signup",
        data={"email": email, "password": "secret123", "password2": "nope", "name": "T"},
        follow_redirects=False,
    )
    # Stays on the signup page (200), no session established.
    assert r.status_code == 200
    assert client.get("/api/personal", follow_redirects=False).status_code == 307
