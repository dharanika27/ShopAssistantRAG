"""Conversational chat interface (E8-S3) — the primary feature UI.

Renders a chat transcript and input. Each submission posts to ``POST /api/chat``
with a stable per-session ``session_id`` (AC-3), appends the user turn and the
grounded assistant reply (AC-1) with up to five inline product cards (AC-2), and
keeps the full transcript visible across the session (AC-6). Multi-turn
refinement works because the same ``session_id`` is reused every turn (AC-4); a
no-match reply shows the friendly message with zero cards (AC-5). A backend
failure is shown as a friendly assistant turn, never a stack trace.

The transcript state and turn logic are pure helpers so they are unit-testable
without a Streamlit runtime; only ``render_chat`` touches ``st.*``.
"""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

import streamlit as st
from api_client import ApiUnavailableError, ChatReply, ProductView
from components.product_card import render_product_card

MAX_INLINE_CARDS = 5
_SESSION_KEY = "chat_session_id"
_TRANSCRIPT_KEY = "chat_transcript"
_WELCOME = (
    "Hi! Describe what you're shopping for and I'll find matching products — "
    "for example, “red Nike shoes under ₹3000”."
)


@dataclass(frozen=True)
class ChatTurn:
    """One entry in the visible transcript (a user message or assistant reply)."""

    role: str
    text: str
    products: list[ProductView] = field(default_factory=list)


class _ChatClient(Protocol):
    """The subset of :class:`ApiClient` the chat needs (the mock boundary)."""

    def post_chat(self, session_id: str, message: str) -> ChatReply: ...


def new_session_id() -> str:
    """Generate a fresh, stable session identifier (AC-3)."""
    return uuid4().hex


def cap_products(products: list[ProductView]) -> list[ProductView]:
    """Limit the inline product cards to at most five (AC-2)."""
    return products[:MAX_INLINE_CARDS]


def append_turn(
    transcript: list[ChatTurn],
    *,
    role: str,
    text: str,
    products: list[ProductView] | None = None,
) -> None:
    """Append a turn, capping assistant products at the inline limit."""
    transcript.append(ChatTurn(role=role, text=text, products=cap_products(products or [])))


def run_chat_turn(
    client: _ChatClient,
    session_id: str,
    message: str,
    transcript: list[ChatTurn],
) -> None:
    """Run one turn: record the user message, call the backend, record the reply."""
    cleaned = message.strip()
    if not cleaned:
        return
    append_turn(transcript, role="user", text=cleaned)
    try:
        reply = client.post_chat(session_id, cleaned)
    except ApiUnavailableError as error:
        append_turn(transcript, role="assistant", text=str(error))
        return
    append_turn(transcript, role="assistant", text=reply.reply, products=reply.products)


def render_chat(client: _ChatClient) -> None:
    """Render the chat transcript and input, handling one turn per submission."""
    session_id = _ensure_session_id()
    transcript = _ensure_transcript()
    st.caption(f"Session: {session_id}")
    _render_transcript(transcript)
    message = st.chat_input("Describe what you're looking for…")
    if message:
        run_chat_turn(client, session_id, message, transcript)
        st.rerun()


def _ensure_session_id() -> str:
    if _SESSION_KEY not in st.session_state:
        st.session_state[_SESSION_KEY] = new_session_id()
    return st.session_state[_SESSION_KEY]


def _ensure_transcript() -> list[ChatTurn]:
    if _TRANSCRIPT_KEY not in st.session_state:
        st.session_state[_TRANSCRIPT_KEY] = [ChatTurn(role="assistant", text=_WELCOME)]
    return st.session_state[_TRANSCRIPT_KEY]


def _render_transcript(transcript: list[ChatTurn]) -> None:
    for turn in transcript:
        with st.chat_message(turn.role):
            st.markdown(turn.text)
            _render_inline_cards(turn.products)


def _render_inline_cards(products: list[ProductView]) -> None:
    if not products:
        return
    columns = st.columns(len(products))
    for column, product in zip(columns, products, strict=False):
        with column:
            render_product_card(product)
