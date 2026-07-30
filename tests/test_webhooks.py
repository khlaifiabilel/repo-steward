import hashlib
import hmac
import json

from fastapi.testclient import TestClient


def _signature(body: bytes) -> str:
    digest = hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _headers(body: bytes, *, event: str = "ping") -> dict[str, str]:
    return {
        "X-Hub-Signature-256": _signature(body),
        "X-GitHub-Delivery": "delivery-123",
        "X-GitHub-Event": event,
        "Content-Type": "application/json",
    }


def test_valid_supported_webhook_is_accepted(client: TestClient) -> None:
    body = b'{"zen":"test"}'
    response = client.post("/webhooks/github", content=body, headers=_headers(body))
    assert response.status_code == 202
    assert response.json() == {"accepted": True, "event": "ping", "delivery_id": "delivery-123"}


def test_installation_webhook_is_validated(client: TestClient) -> None:
    body = json.dumps(
        {
            "action": "created",
            "installation": {
                "id": 42,
                "account": {"id": 7, "login": "acme", "extra": "ignored"},
            },
        }
    ).encode()
    response = client.post(
        "/webhooks/github", content=body, headers=_headers(body, event="installation")
    )
    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "event": "installation",
        "delivery_id": "delivery-123",
        "action": "created",
        "installation_id": 42,
    }


def test_installation_repositories_webhook_is_validated(client: TestClient) -> None:
    body = json.dumps(
        {
            "action": "added",
            "installation": {"id": 42, "account": {"id": 7, "login": "acme"}},
            "repositories_added": [{"id": 99, "name": "widget"}],
            "repositories_removed": [],
        }
    ).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers=_headers(body, event="installation_repositories"),
    )
    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "event": "installation_repositories",
        "delivery_id": "delivery-123",
        "action": "added",
        "installation_id": 42,
    }


def test_marketplace_purchase_webhook_is_validated(client: TestClient) -> None:
    body = json.dumps(
        {
            "action": "purchased",
            "marketplace_purchase": {
                "account": {"id": 7, "login": "acme"},
                "plan": {
                    "id": 3,
                    "number": 1,
                    "name": "Free",
                    "monthly_price_in_cents": 0,
                    "yearly_price_in_cents": 0,
                },
            },
        }
    ).encode()
    response = client.post(
        "/webhooks/github", content=body, headers=_headers(body, event="marketplace_purchase")
    )
    assert response.status_code == 202
    assert response.json() == {
        "accepted": True,
        "event": "marketplace_purchase",
        "delivery_id": "delivery-123",
        "action": "purchased",
        "account_id": 7,
        "plan_number": 1,
    }


def test_lifecycle_webhook_rejects_invalid_payload(client: TestClient) -> None:
    body = b"{}"
    response = client.post(
        "/webhooks/github", content=body, headers=_headers(body, event="installation")
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid GitHub webhook payload"}


def test_unsupported_webhook_event_is_rejected(client: TestClient) -> None:
    body = b"{}"
    response = client.post("/webhooks/github", content=body, headers=_headers(body, event="issues"))
    assert response.status_code == 422


def test_missing_signature_is_rejected(client: TestClient) -> None:
    response = client.post("/webhooks/github", content=b"{}")
    assert response.status_code == 401


def test_invalid_signature_is_rejected_before_malformed_json(client: TestClient) -> None:
    response = client.post(
        "/webhooks/github",
        content=b"not-json",
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid webhook signature"}


def test_signed_malformed_json_is_rejected(client: TestClient) -> None:
    body = b"not-json"
    response = client.post("/webhooks/github", content=body, headers=_headers(body))
    assert response.status_code == 400
    assert response.json() == {"detail": "Malformed JSON payload"}


def test_signed_non_object_json_is_rejected(client: TestClient) -> None:
    body = b"[]"
    response = client.post("/webhooks/github", content=body, headers=_headers(body))
    assert response.status_code == 400


def test_signed_payload_requires_delivery_and_event_headers(client: TestClient) -> None:
    body = b"{}"
    response = client.post(
        "/webhooks/github", content=body, headers={"X-Hub-Signature-256": _signature(body)}
    )
    assert response.status_code == 400


def test_oversized_webhook_is_rejected_before_invalid_signature() -> None:
    from repo_steward.app import create_app
    from repo_steward.config import Settings

    with TestClient(
        create_app(Settings(max_request_body_bytes=16, github_webhook_secret="secret"))
    ) as limited:
        response = limited.post(
            "/webhooks/github",
            content=b"x" * 17,
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        )
    assert response.status_code == 413


def test_webhook_headers_are_length_limited(client: TestClient) -> None:
    body = b"{}"
    headers = _headers(body)
    headers["X-GitHub-Delivery"] = "x" * 129
    assert client.post("/webhooks/github", content=body, headers=headers).status_code == 422
