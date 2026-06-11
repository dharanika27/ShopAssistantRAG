"""FastAPI application factory and lifespan (E7-S1).

``create_app`` assembles the application: it installs CORS (origins read from
config, never wildcarded — code-gen CORS rule), the request-id middleware, the
typed-error handlers, and the route modules. A lifespan builds the process-wide
object graph (settings, product repository, chat orchestrator) once at startup
and stores it on ``app.state`` so dependency providers can hand the same
instances to every request.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.dependencies import (
    build_chat_orchestrator,
    get_chat_orchestrator,
    get_product_repository,
)
from backend.api.middleware import RequestIdMiddleware, register_error_handlers
from backend.api.routes import catalog, chat, health
from backend.core.config import Settings
from backend.core.errors import ConfigError
from backend.core.logging import get_logger
from backend.repositories.product_repository import ProductRepository

logger = get_logger(__name__)

_TITLE = "ShopAssistant Backend"
_VERSION = "1.0"


def _real_providers_overridden(app: FastAPI) -> bool:
    """True when tests have substituted the orchestrator/repository providers.

    When overridden, the live object graph is never read, so building it (which
    requires real secrets) is skipped — letting integration tests start the app
    without a populated environment while production still fails fast on a
    missing configuration.
    """
    overrides = app.dependency_overrides
    return get_chat_orchestrator in overrides and get_product_repository in overrides


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the shared object graph at startup; nothing to dispose at shutdown.

    The repository opens MySQL connections per call and the SDK wrappers hold no
    pooled resources, so teardown is a no-op for this demo-scale deployment.
    """
    if not _real_providers_overridden(app):
        settings = Settings()
        repository = ProductRepository(settings)
        app.state.settings = settings
        app.state.product_repository = repository
        app.state.chat_orchestrator = build_chat_orchestrator(settings, repository)
        # Surface the resolved provider/model config at runtime (no secrets) so
        # the active LLM provider and models — which can be shadowed by OS env
        # vars over .env — are visible in the logs when diagnosing issues.
        logger.info(
            "api.config_resolved",
            extra={
                "llm_provider": settings.LLM_PROVIDER,
                "generation_model": settings.active_generation_model(),
                "embedding_model": settings.EMBEDDING_MODEL,
                "embedding_dimension": settings.EMBEDDING_DIM,
                "pinecone_index": settings.PINECONE_INDEX_NAME,
            },
        )
    logger.info("api.startup", extra={"version": _VERSION})
    yield
    logger.info("api.shutdown", extra={"version": _VERSION})


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application (E7-S1)."""
    app = FastAPI(title=_TITLE, version=_VERSION, lifespan=lifespan)
    _install_cors(app)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(catalog.router)
    return app


def _install_cors(app: FastAPI) -> None:
    """Add CORS allowing only the configured frontend origins (AC-2)."""
    origins = _resolve_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


def _resolve_origins() -> list[str]:
    """Read allowed origins from config, defaulting to the Streamlit origin.

    Falls back to the default when config cannot be loaded (e.g. in a test that
    constructs the app without a populated environment) so CORS is always
    configured and never wildcarded.
    """
    try:
        return Settings().allowed_origins_list()
    except ConfigError:
        return ["http://localhost:8501"]
