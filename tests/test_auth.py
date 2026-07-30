import asyncio
from collections.abc import Awaitable

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from repo_steward.auth import create_app_jwt, exchange_installation_token
from repo_steward.github import (
    GitHubAPIError,
    GitHubProtocolError,
    GitHubTimeoutError,
    GitHubTransportError,
)


def run(coroutine: Awaitable[str]) -> str:
    return asyncio.run(coroutine)


@pytest.fixture(scope="module")
def test_keys() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_key = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_key, public_key


def test_app_jwt_has_short_lived_expected_claims(test_keys: tuple[str, str]) -> None:
    private_key, public_key = test_keys
    token = create_app_jwt(12345, private_key, now=1_800_000_000)
    claims = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims == {"iat": 1_799_999_940, "exp": 1_800_000_540, "iss": "12345"}
    assert private_key not in token


def test_installation_token_exchange_uses_expected_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/app/installations/42/access_tokens"
        assert request.headers["Authorization"] == "Bearer app-jwt"
        return httpx.Response(201, json={"token": "ephemeral-installation-token"})

    token = run(exchange_installation_token("app-jwt", 42, transport=httpx.MockTransport(handler)))
    assert token == "ephemeral-installation-token"


def test_installation_exchange_errors_are_typed_and_redacted() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "includes unsafe upstream detail"})

    with pytest.raises(GitHubAPIError, match="installation token exchange failed") as caught:
        run(exchange_installation_token("secret-jwt", 42, transport=httpx.MockTransport(handler)))
    assert "secret-jwt" not in str(caught.value)


def test_installation_exchange_requires_token_in_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"expires_at": "later"})

    with pytest.raises(GitHubProtocolError, match="no token"):
        run(exchange_installation_token("app-jwt", 42, transport=httpx.MockTransport(handler)))


def test_auth_identifiers_must_be_positive(test_keys: tuple[str, str]) -> None:
    with pytest.raises(ValueError, match="App ID"):
        create_app_jwt(0, test_keys[0])
    with pytest.raises(ValueError, match="installation ID"):
        run(exchange_installation_token("app-jwt", 0))


def test_installation_exchange_transport_failures_are_typed() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("unsafe", request=request)

    with pytest.raises(GitHubTimeoutError):
        run(exchange_installation_token("jwt", 1, transport=httpx.MockTransport(timeout)))

    def transport(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unsafe", request=request)

    with pytest.raises(GitHubTransportError):
        run(exchange_installation_token("jwt", 1, transport=httpx.MockTransport(transport)))
