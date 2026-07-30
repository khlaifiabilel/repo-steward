"""FastAPI application factory."""

from fastapi import FastAPI

from repo_steward.config import Settings, get_settings
from repo_steward.logging import configure_logging
from repo_steward.middleware import SecurityMiddleware
from repo_steward.routes import api_router, webhook_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    application = FastAPI(
        title="repo-steward",
        version="0.1.0",
        description="Private-beta deterministic repository health API",
    )
    application.state.settings = resolved

    @application.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(api_router)
    application.include_router(webhook_router)
    application.add_middleware(SecurityMiddleware, max_body_bytes=resolved.max_request_body_bytes)
    return application


app = create_app()
