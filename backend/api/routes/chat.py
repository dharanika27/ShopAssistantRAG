"""Chat endpoint — ``POST /api/chat`` (E7-S2).

The primary RAG entry point. Validates the request body (non-empty
``session_id``/``message`` via the schema; blank input yields 422), forwards the
turn to the injected :class:`ChatOrchestrator`, and serializes the grounded
reply plus up to five hydrated products through :class:`ChatResponse`.

Distinct ``session_id`` values map to independent orchestrator state (AC-3); the
orchestrator owns conversation memory. Downstream Gemini/Pinecone/MySQL failures
surface as typed :class:`AppError`s and are mapped to the BRD envelope by the
error middleware (E7-S1) — this handler does not catch them (AC-6).
"""

from fastapi import APIRouter

from backend.api.dependencies import ChatOrchestratorDep
from backend.api.schemas import ChatRequest, ChatResponse, ProductOut
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["chat"])

MAX_PRODUCT_CARDS = 5


@router.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, orchestrator: ChatOrchestratorDep) -> ChatResponse:
    """Run one conversational turn and return the grounded reply (AC-1, AC-2)."""
    logger.info("api.chat.received", extra={"session_id": request.session_id})
    result = orchestrator.handle_turn(request.session_id, request.message)
    products = [ProductOut.from_domain(product) for product in result.products[:MAX_PRODUCT_CARDS]]
    return ChatResponse(reply=result.reply, products=products)
