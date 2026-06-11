"""Session-scoped conversational memory & filter state (E6-S1).

The conversational core's state substrate and the project's highest-risk area
(BRD R-1, session-memory-design.md). A process-local :class:`QueryStateManager`
holds one independent :class:`SessionState` per ``session_id``, each carrying:

* an accumulating :class:`QueryFilters` object (refined across turns, AC-1);
* a bounded history of conversation :class:`Turn` records (AC-5);
* the last category seen, used by the orchestrator (E6-S3) to detect a category
  change.

State lives only in memory for the active process — there is no persistence, so
all sessions are lost on restart (AC-4). A process-local dict is sufficient for
the BRD's low-concurrency target; Redis would be over-engineering (design D-2).

This module owns only the state container and its mutation primitives. The
intent-decision logic (merge vs. reset vs. cheaper) lives in the orchestrator
(E6-S3); keeping it out of here makes both independently testable.
"""

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from backend.core.logging import get_logger
from backend.domain.enums import Category
from backend.domain.models import QueryFilters

logger = get_logger(__name__)

DEFAULT_HISTORY_LIMIT = 10


class TurnRole(StrEnum):
    """Author of a conversation turn (session-memory-design.md §2)."""

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Turn:
    """A single conversation turn — who said it and what was said."""

    role: TurnRole
    message: str


@dataclass
class SessionState:
    """Mutable per-session state: accumulating filters + bounded history.

    Each session owns its own :class:`QueryFilters` instance so mutating one
    session never affects another (E6-S1 AC-2).
    """

    session_id: str
    filters: QueryFilters = field(default_factory=QueryFilters)
    history: deque[Turn] = field(default_factory=deque)
    last_category: Category | None = None
    last_result_min_price: Decimal | None = None


class QueryStateManager:
    """In-memory store of isolated, per-session conversational state (E6-S1).

    Sessions are created lazily on first contact. Nothing is persisted, so a
    freshly constructed manager starts empty (AC-4). ``history_limit`` bounds
    each session's turn history so a long-running session cannot grow without
    limit (AC-5).
    """

    def __init__(self, *, history_limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self._history_limit = history_limit
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, session_id: str) -> SessionState:
        """Return the session's state, creating an empty one on first contact (AC-1)."""
        state = self._sessions.get(session_id)
        if state is None:
            state = SessionState(
                session_id=session_id,
                history=deque(maxlen=self._history_limit),
            )
            self._sessions[session_id] = state
            logger.info("query_state.session_created", extra={"session_id": session_id})
        return state

    def reset(self, session_id: str) -> SessionState:
        """Clear the session's filters and last category to empty (E6-S1 AC-3).

        History is intentionally preserved so the conversation transcript stays
        intact across an explicit filter reset.
        """
        state = self.get_or_create(session_id)
        state.filters = QueryFilters()
        state.last_category = None
        state.last_result_min_price = None
        logger.info("query_state.session_reset", extra={"session_id": session_id})
        return state

    def append_turn(self, session_id: str, role: TurnRole, message: str) -> None:
        """Record a conversation turn, dropping the oldest beyond the limit (AC-5)."""
        state = self.get_or_create(session_id)
        state.history.append(Turn(role=role, message=message))
