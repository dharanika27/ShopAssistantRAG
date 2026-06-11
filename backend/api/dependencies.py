"""FastAPI dependency providers (E7-S1).

The single place that assembles the application's object graph and hands it to
route handlers via ``Depends(...)``. The composed singletons (settings, the
product repository, and the fully-wired chat orchestrator) are created once in
the lifespan (see :mod:`backend.api.main`) and stored on ``app.state``; these
providers simply read them back so every request shares the same instances.

Integration tests override :func:`get_chat_orchestrator` and
:func:`get_product_repository` with fakes, so the live service wiring here never
runs under test — the wiring itself is exercised by the deployed app.
"""

from typing import Annotated

from fastapi import Depends, Request

from backend.core.config import Settings
from backend.repositories.pinecone_client import PineconeClient
from backend.repositories.product_repository import ProductRepository
from backend.services.answer_generator import AnswerGenerator
from backend.services.chat_orchestrator import ChatOrchestrator
from backend.services.embedding_client import EmbeddingClient
from backend.services.filter_extractor import FilterExtractor
from backend.services.hybrid_retriever import HybridRetriever
from backend.services.hydrator import ProductHydrator
from backend.services.llm_provider import build_completion_fn
from backend.services.query_state import QueryStateManager


def build_chat_orchestrator(
    settings: Settings, repository: ProductRepository
) -> ChatOrchestrator:
    """Wire the full conversational object graph from ``settings`` (E7-S2).

    Constructed once at startup. Each collaborator is the project's typed
    wrapper, so no external SDK type crosses into the orchestrator. The LLM
    generation provider (Groq by default) is resolved once and shared by both
    filter extraction and answer generation, so a single Groq client backs the
    whole turn. Embeddings stay on Gemini via :class:`EmbeddingClient`.
    """
    embedding_client = EmbeddingClient(settings)
    pinecone_client = PineconeClient(settings)
    completion_fn = build_completion_fn(settings)
    return ChatOrchestrator(
        filter_extractor=FilterExtractor(settings, extract_fn=completion_fn),
        state_manager=QueryStateManager(),
        retriever=HybridRetriever(
            pinecone_client=pinecone_client, embedding_client=embedding_client
        ),
        hydrator=ProductHydrator(repository=repository),
        answer_generator=AnswerGenerator(settings, generate_fn=completion_fn),
    )


def get_settings(request: Request) -> Settings:
    """Return the process-wide :class:`Settings` created at startup."""
    return request.app.state.settings


def get_product_repository(request: Request) -> ProductRepository:
    """Return the shared :class:`ProductRepository` created at startup."""
    return request.app.state.product_repository


def get_chat_orchestrator(request: Request) -> ChatOrchestrator:
    """Return the shared :class:`ChatOrchestrator` created at startup."""
    return request.app.state.chat_orchestrator


SettingsDep = Annotated[Settings, Depends(get_settings)]
ProductRepositoryDep = Annotated[ProductRepository, Depends(get_product_repository)]
ChatOrchestratorDep = Annotated[ChatOrchestrator, Depends(get_chat_orchestrator)]
