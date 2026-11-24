from app.core.logging import REDACTED, redact_sensitive


def test_redacts_sensitive_keys_recursively() -> None:
    event = {
        "event": "call",
        "api_key": "abc",
        "headers": {"Authorization": "Bearer x", "Accept": "json"},
        "items": [{"password": "p"}],
        "path": "/x",
    }
    out = redact_sensitive(None, "info", event)
    assert out["api_key"] == REDACTED
    assert out["headers"] == {"Authorization": REDACTED, "Accept": "json"}
    assert out["items"] == [{"password": REDACTED}]
    assert out["path"] == "/x"
    assert out["event"] == "call"
