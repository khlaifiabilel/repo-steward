from repo_steward.webhooks import verify_signature


def test_signature_format_is_strict() -> None:
    assert verify_signature(b"body", None, "secret") is False
    assert verify_signature(b"body", "md5=abc", "secret") is False
    assert verify_signature(b"body", "sha256=short", "secret") is False
