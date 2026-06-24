def test_credentials_roundtrip(client):
    # client fixture triggers startup -> tables created
    from connections.credentials import (
        set_credentials,
        get_credentials,
        get_all_credentials,
        delete_credentials,
    )

    set_credentials("u1", "gerrit", {"username": "alice", "password": "s3cret"})
    assert get_credentials("u1", "gerrit") == {"username": "alice", "password": "s3cret"}

    # Exposed as session-style keys
    allc = get_all_credentials("u1")
    assert allc["gerrit_username"] == "alice"
    assert allc["gerrit_password"] == "s3cret"

    delete_credentials("u1", "gerrit")
    assert get_credentials("u1", "gerrit") == {}


def test_credentials_encrypted_at_rest(client):
    from connections.credentials import set_credentials
    from database import session_scope
    from models import Credential

    set_credentials("u2", "slack", {"token": "xoxp-supersecret", "name": "bob"})
    with session_scope() as s:
        row = s.query(Credential).filter(Credential.user_id == "u2").one()
        # The plaintext token must not appear in the stored payload.
        assert "xoxp-supersecret" not in row.payload
        assert "bob" not in row.payload


def test_disconnect_unknown_service(demo_client):
    assert demo_client.post("/api/disconnect/notreal").status_code == 404
