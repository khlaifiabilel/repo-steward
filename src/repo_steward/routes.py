"""FastAPI route definitions."""

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError

from repo_steward.config import Settings
from repo_steward.github import GitHubClient, GitHubError, GitHubTimeoutError
from repo_steward.models import (
    HealthReport,
    InstallationRepositoriesWebhook,
    InstallationWebhook,
    InventoryRequest,
    InventorySummary,
    MarketplacePurchaseWebhook,
    OwnerAnalysis,
    RepositorySnapshot,
)
from repo_steward.services import analyze, inventory
from repo_steward.webhooks import verify_signature

logger = logging.getLogger(__name__)
webhook_router = APIRouter()


async def require_api_key(
    request: Request,
    supplied_key: Annotated[str | None, Header(alias="X-Repo-Steward-Key", max_length=256)] = None,
) -> None:
    configured = request.app.state.settings.api_key
    if configured is None:
        return
    supplied_digest = hashlib.sha256((supplied_key or "").encode()).digest()
    expected_digest = hashlib.sha256(configured.get_secret_value().encode()).digest()
    if not hmac.compare_digest(supplied_digest, expected_digest):
        raise HTTPException(status_code=401, detail="Invalid API key")


api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@api_router.post("/analyze", response_model=HealthReport)
async def analyze_snapshot(snapshot: RepositorySnapshot) -> HealthReport:
    return analyze(snapshot)


@api_router.post("/inventory", response_model=InventorySummary)
async def inventory_snapshots(request: InventoryRequest) -> InventorySummary:
    return inventory(request.snapshots)


@api_router.post("/github/owners/{owner}/analyze", response_model=OwnerAnalysis)
async def analyze_owner(owner: str, request: Request) -> OwnerAnalysis:
    settings: Settings = request.app.state.settings
    if owner.casefold() not in settings.github_allowed_owners:
        raise HTTPException(status_code=403, detail="GitHub owner is not allowed")
    if settings.github_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub credentials are not configured",
        )
    try:
        async with asyncio.timeout(settings.github_owner_timeout_seconds):
            async with GitHubClient(
                settings.github_token.get_secret_value(),
                base_url=settings.github_api_url,
                timeout=settings.github_request_timeout_seconds,
                max_pages=settings.github_max_pages,
                max_tree_requests=settings.github_max_tree_requests,
                max_repositories=settings.github_max_repositories,
                max_requests=settings.github_max_requests,
                max_response_bytes=settings.github_max_response_bytes,
                max_tree_entries=settings.github_max_tree_entries,
                max_queued_trees=settings.github_max_queued_trees,
                max_retained_paths=settings.github_max_retained_paths,
                allow_localhost_http=settings.environment.casefold() == "test",
            ) as client:
                snapshots = await client.owner_snapshots(owner)
    except (TimeoutError, GitHubTimeoutError) as exc:
        logger.warning(
            "GitHub read timed out", extra={"correlation_id": request.state.correlation_id}
        )
        raise HTTPException(status_code=504, detail="GitHub request timed out") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid GitHub identifier") from exc
    except GitHubError as exc:
        logger.warning("GitHub read failed", extra={"correlation_id": request.state.correlation_id})
        raise HTTPException(status_code=502, detail="GitHub request failed") from exc
    return OwnerAnalysis(owner=owner, reports=tuple(analyze(snapshot) for snapshot in snapshots))


@webhook_router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256", max_length=71)] = None,
    delivery_id: Annotated[
        str | None, Header(alias="X-GitHub-Delivery", min_length=1, max_length=128)
    ] = None,
    event: Annotated[
        Literal[
            "ping",
            "installation",
            "installation_repositories",
            "marketplace_purchase",
            "push",
        ]
        | None,
        Header(alias="X-GitHub-Event", max_length=32),
    ] = None,
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    if settings.github_webhook_secret is None:
        raise HTTPException(status_code=503, detail="Webhook secret is not configured")
    body = await request.body()
    if not verify_signature(body, signature, settings.github_webhook_secret.get_secret_value()):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    if not delivery_id or not event:
        raise HTTPException(status_code=400, detail="Missing GitHub webhook headers")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Malformed JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    event_metadata: dict[str, str | int] = {}
    try:
        if event == "installation":
            installation_event = InstallationWebhook.model_validate(payload)
            event_metadata = {
                "action": installation_event.action,
                "installation_id": installation_event.installation.id,
            }
        elif event == "installation_repositories":
            repositories_event = InstallationRepositoriesWebhook.model_validate(payload)
            event_metadata = {
                "action": repositories_event.action,
                "installation_id": repositories_event.installation.id,
            }
        elif event == "marketplace_purchase":
            purchase_event = MarketplacePurchaseWebhook.model_validate(payload)
            event_metadata = {
                "action": purchase_event.action,
                "account_id": purchase_event.marketplace_purchase.account.id,
                "plan_number": purchase_event.marketplace_purchase.plan.number,
            }
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid GitHub webhook payload") from exc

    logger.info(
        "Webhook received",
        extra={
            "delivery_id": delivery_id,
            "event": event,
            "correlation_id": request.state.correlation_id,
            **event_metadata,
        },
    )
    return {"accepted": True, "event": event, "delivery_id": delivery_id, **event_metadata}
