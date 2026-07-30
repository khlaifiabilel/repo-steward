"""GitHub App authentication helpers."""

import time
from typing import Any

import httpx
import jwt

from repo_steward.github import (
    GitHubAPIError,
    GitHubProtocolError,
    GitHubTimeoutError,
    GitHubTransportError,
    validate_base_url,
)


def create_app_jwt(app_id: int, private_key: str, *, now: int | None = None) -> str:
    """Create a short-lived RS256 GitHub App JWT."""
    if app_id <= 0:
        raise ValueError("GitHub App ID must be positive")
    issued_at = int(time.time()) if now is None else now
    claims = {"iat": issued_at - 60, "exp": issued_at + 540, "iss": str(app_id)}
    return jwt.encode(claims, private_key, algorithm="RS256")


async def exchange_installation_token(
    app_jwt: str,
    installation_id: int,
    *,
    base_url: str = "https://api.github.com",
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Exchange an App JWT for a short-lived installation token."""
    if installation_id <= 0:
        raise ValueError("GitHub installation ID must be positive")
    if not 0 < timeout <= 60:
        raise ValueError("timeout must be greater than zero and at most 60")
    try:
        async with httpx.AsyncClient(
            base_url=validate_base_url(base_url),
            timeout=httpx.Timeout(timeout),
            transport=transport,
        ) as client:
            response = await client.post(
                f"/app/installations/{installation_id}/access_tokens",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {app_jwt}",
                    "User-Agent": "repo-steward/0.1.0",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    except httpx.TimeoutException as exc:
        raise GitHubTimeoutError("GitHub token exchange timed out") from exc
    except httpx.TransportError as exc:
        raise GitHubTransportError("GitHub token exchange transport failed") from exc
    if response.is_error:
        raise GitHubAPIError(response.status_code, "installation token exchange failed")
    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise GitHubProtocolError("token exchange returned non-JSON content") from exc
    if not isinstance(payload, dict):
        raise GitHubProtocolError("token exchange response has no token")
    token = payload.get("token")
    if not isinstance(token, str):
        raise GitHubProtocolError("token exchange response has no token")
    return token
