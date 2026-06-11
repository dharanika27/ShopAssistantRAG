"""Unit tests for the chat interface logic (E8-S3).

The Streamlit transcript rendering is thin; the testable logic is session-id
stability, transcript accumulation across turns (multi-turn refinement + visible
history), capping inline cards at five, and translating a backend failure into a
friendly transcript turn rather than a stack trace.
"""

from decimal import Decimal

from api_client import ApiUnavailableError, ChatReply, ProductView
from components.chat import (
    MAX_INLINE_CARDS,
    ChatTurn,
    append_turn,
    cap_products,
    new_session_id,
    run_chat_turn,
)


class _FakeClient:
    """Stand-in for :class:`ApiClient` recording chat calls (the seam under test)."""

    def __init__(self, reply: ChatReply | ApiUnavailableError) -> None:
        self._reply = reply
        self.calls: list[tuple[str, str]] = []

    def post_chat(self, session_id: str, message: str) -> ChatReply:
        self.calls.append((session_id, message))
        if isinstance(self._reply, ApiUnavailableError):
            raise self._reply
        return self._reply


def _product(product_id: str, color: str) -> ProductView:
    return ProductView(
        product_id=product_id,
        name=f"Nike {product_id}",
        description="A shoe.",
        brand="Nike",
        category="Shoes",
        gender="Men",
        color=color,
        price=Decimal("2799.00"),
        image_url=None,
        stock=5,
        in_stock=True,
        tags=["Running"],
    )


def test_new_session_id_is_nonempty_and_unique() -> None:
    # Act
    first, second = new_session_id(), new_session_id()
    # Assert — AC-3: a stable id is generated; two sessions differ
    assert first and second
    assert first != second


def test_cap_products_limits_to_five() -> None:
    # Arrange — AC-2: at most 5 cards render inline
    products = [_product(f"P{i}", "Red") for i in range(8)]
    # Act
    capped = cap_products(products)
    # Assert
    assert len(capped) == MAX_INLINE_CARDS
    assert [p.product_id for p in capped] == ["P0", "P1", "P2", "P3", "P4"]


def test_run_chat_turn_sends_session_id_and_records_both_turns() -> None:
    # Arrange
    reply = ChatReply(reply="Here are some Nike shoes.", products=[_product("P1", "Red")])
    client = _FakeClient(reply)
    transcript: list[ChatTurn] = []
    # Act — AC-1, AC-3
    run_chat_turn(client, "sess-abc", "Show me Nike shoes", transcript)
    # Assert
    assert client.calls == [("sess-abc", "Show me Nike shoes")]
    assert [turn.role for turn in transcript] == ["user", "assistant"]
    assert transcript[0].text == "Show me Nike shoes"
    assert transcript[1].text == "Here are some Nike shoes."
    assert len(transcript[1].products) == 1


def test_multi_turn_refinement_preserves_history_and_same_session() -> None:
    # Arrange — AC-4, AC-6: follow-up within the same session, history retained
    transcript: list[ChatTurn] = []
    first = _FakeClient(ChatReply(reply="All Nike shoes.", products=[_product("P1", "Red"),
                                                                      _product("P2", "Black")]))
    run_chat_turn(first, "sess-abc", "Show me Nike shoes", transcript)
    second = _FakeClient(ChatReply(reply="Only the red ones.", products=[_product("P1", "Red")]))
    # Act
    run_chat_turn(second, "sess-abc", "only red ones", transcript)
    # Assert — same session id reused; full transcript preserved
    assert second.calls == [("sess-abc", "only red ones")]
    assert [t.text for t in transcript] == [
        "Show me Nike shoes",
        "All Nike shoes.",
        "only red ones",
        "Only the red ones.",
    ]


def test_no_match_turn_shows_message_and_zero_cards() -> None:
    # Arrange — AC-5
    no_match = ChatReply(
        reply="I couldn't find anything matching that. We carry Shoes, Clothing, "
        "Accessories, Sportswear and Bags — want to browse one of those?",
        products=[],
    )
    client = _FakeClient(no_match)
    transcript: list[ChatTurn] = []
    # Act
    run_chat_turn(client, "sess-abc", "show me laptops", transcript)
    # Assert
    assert transcript[1].products == []
    assert "couldn't find" in transcript[1].text


def test_backend_failure_becomes_friendly_assistant_turn() -> None:
    # Arrange — AC: friendly message, never a stack trace
    error = ApiUnavailableError(
        "The AI assistant is temporarily unavailable. Please try again in a few moments.",
        code="GEMINI_UNAVAILABLE",
    )
    client = _FakeClient(error)
    transcript: list[ChatTurn] = []
    # Act
    run_chat_turn(client, "sess-abc", "Show me Nike shoes", transcript)
    # Assert — user turn + friendly assistant turn, no products
    assert [t.role for t in transcript] == ["user", "assistant"]
    assert transcript[1].products == []
    assert "temporarily unavailable" in transcript[1].text


def test_run_chat_turn_ignores_blank_message() -> None:
    # Arrange — empty input would be a 422 server-side; the UI must not call
    client = _FakeClient(ChatReply(reply="unused", products=[]))
    transcript: list[ChatTurn] = []
    # Act
    run_chat_turn(client, "sess-abc", "   ", transcript)
    # Assert
    assert client.calls == []
    assert transcript == []


def test_append_turn_caps_assistant_products() -> None:
    # Arrange
    transcript: list[ChatTurn] = []
    products = [_product(f"P{i}", "Red") for i in range(7)]
    # Act
    append_turn(transcript, role="assistant", text="Here you go.", products=products)
    # Assert
    assert len(transcript[0].products) == MAX_INLINE_CARDS
