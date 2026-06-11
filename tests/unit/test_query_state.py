"""Unit tests for E6-S1 — Session-scoped conversational memory & filter state.

The query-state manager is pure in-memory business logic with no external
boundary, so nothing is mocked. These tests assert session isolation (AC-2),
on-demand reset (AC-3), and bounded turn history (AC-5). In-memory-only /
no-persistence (AC-4) is a structural property verified by the absence of any
I/O dependency and by a fresh manager starting empty.
"""

from decimal import Decimal

from backend.domain.enums import Category
from backend.domain.models import QueryFilters
from backend.services.query_state import QueryStateManager, TurnRole

_HISTORY_LIMIT = 10


class TestGetOrCreate:
    def test_first_contact_creates_empty_isolated_state(self) -> None:
        manager = QueryStateManager()

        state = manager.get_or_create("session-alpha")

        assert state.session_id == "session-alpha"
        assert state.filters == QueryFilters()
        assert list(state.history) == []
        assert state.last_category is None

    def test_repeated_calls_return_the_same_state(self) -> None:
        manager = QueryStateManager()

        first = manager.get_or_create("session-alpha")
        first.filters.brand = "Nike"
        second = manager.get_or_create("session-alpha")

        assert second is first
        assert second.filters.brand == "Nike"


class TestSessionIsolation:
    def test_mutating_one_session_does_not_affect_another(self) -> None:
        manager = QueryStateManager()
        alpha = manager.get_or_create("session-alpha")
        beta = manager.get_or_create("session-beta")

        alpha.filters.brand = "Nike"
        alpha.filters.category = Category.SHOES

        assert beta.filters.brand is None
        assert beta.filters.category is None

    def test_each_session_has_an_independent_filters_object(self) -> None:
        manager = QueryStateManager()

        alpha = manager.get_or_create("session-alpha")
        beta = manager.get_or_create("session-beta")

        assert alpha.filters is not beta.filters


class TestReset:
    def test_reset_clears_filters_and_last_category(self) -> None:
        manager = QueryStateManager()
        state = manager.get_or_create("session-alpha")
        state.filters = QueryFilters(brand="Nike", category=Category.SHOES)
        state.last_category = Category.SHOES

        manager.reset("session-alpha")

        refreshed = manager.get_or_create("session-alpha")
        assert refreshed.filters == QueryFilters()
        assert refreshed.last_category is None

    def test_reset_only_affects_the_target_session(self) -> None:
        manager = QueryStateManager()
        manager.get_or_create("session-alpha").filters.brand = "Nike"
        manager.get_or_create("session-beta").filters.brand = "Adidas"

        manager.reset("session-alpha")

        assert manager.get_or_create("session-beta").filters.brand == "Adidas"

    def test_reset_of_unknown_session_creates_empty_state(self) -> None:
        manager = QueryStateManager()

        manager.reset("never-seen")

        assert manager.get_or_create("never-seen").filters == QueryFilters()


class TestTurnHistory:
    def test_append_turn_records_role_and_message_in_order(self) -> None:
        manager = QueryStateManager()

        manager.append_turn("session-alpha", TurnRole.USER, "Show me Nike shoes")
        manager.append_turn(
            "session-alpha", TurnRole.ASSISTANT, "Here are three options."
        )

        history = list(manager.get_or_create("session-alpha").history)
        assert [(turn.role, turn.message) for turn in history] == [
            (TurnRole.USER, "Show me Nike shoes"),
            (TurnRole.ASSISTANT, "Here are three options."),
        ]

    def test_history_is_bounded_and_drops_oldest_turns(self) -> None:
        manager = QueryStateManager()

        for index in range(_HISTORY_LIMIT + 4):
            manager.append_turn("session-alpha", TurnRole.USER, f"message {index}")

        history = list(manager.get_or_create("session-alpha").history)
        assert len(history) == _HISTORY_LIMIT
        assert history[0].message == "message 4"
        assert history[-1].message == f"message {_HISTORY_LIMIT + 3}"

    def test_history_is_isolated_per_session(self) -> None:
        manager = QueryStateManager()

        manager.append_turn("session-alpha", TurnRole.USER, "alpha message")

        assert list(manager.get_or_create("session-beta").history) == []


class TestConfigurableHistoryLimit:
    def test_custom_history_limit_is_respected(self) -> None:
        manager = QueryStateManager(history_limit=2)

        for index in range(5):
            manager.append_turn("session-alpha", TurnRole.USER, f"m{index}")

        history = list(manager.get_or_create("session-alpha").history)
        assert [turn.message for turn in history] == ["m3", "m4"]


class TestFreshManagerHasNoPersistedState:
    def test_a_new_manager_does_not_see_prior_manager_sessions(self) -> None:
        first = QueryStateManager()
        first.get_or_create("session-alpha").filters.max_price = Decimal("2000")

        second = QueryStateManager()

        assert second.get_or_create("session-alpha").filters.max_price is None
