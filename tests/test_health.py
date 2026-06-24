def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_version(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    assert "version" in r.json()
