from __future__ import annotations

from shared.contracts import (
    ConversationTurn,
    Intent,
    PendingActionProposal,
    SessionContext,
)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionContext] = {}
        self._pending_actions: dict[tuple[str, str], PendingActionProposal] = {}
        self._pending_action_index: dict[str, tuple[str, str]] = {}
        self._processed_events: set[str] = set()

    def get_or_create(self, session_id: str) -> SessionContext:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionContext(session_id=session_id)
        return self._sessions[session_id]

    def append_user_turn(self, session_id: str, text: str) -> SessionContext:
        session = self.get_or_create(session_id)
        session.turns.append(ConversationTurn(role="user", text=text))
        return session

    def append_assistant_turn(
        self, session_id: str, text: str, intent: Intent | None = None
    ) -> SessionContext:
        session = self.get_or_create(session_id)
        session.turns.append(ConversationTurn(role="assistant", text=text))
        if intent is not None:
            session.last_intent = intent
        return session

    def append_system_turn(self, session_id: str, text: str) -> SessionContext:
        session = self.get_or_create(session_id)
        session.turns.append(ConversationTurn(role="system", text=text))
        return session

    def get_pending_action(self, session_id: str, user_id: str) -> PendingActionProposal | None:
        return self._pending_actions.get((session_id, user_id))

    def set_pending_action(
        self, session_id: str, user_id: str, pending_action: PendingActionProposal
    ) -> PendingActionProposal:
        existing = self._pending_actions.get((session_id, user_id))
        if existing is not None:
            _ = self._pending_action_index.pop(existing.pending_action_id, None)
        self._pending_actions[(session_id, user_id)] = pending_action
        self._pending_action_index[pending_action.pending_action_id] = (
            session_id,
            user_id,
        )
        return pending_action

    def clear_pending_action(self, session_id: str, user_id: str) -> PendingActionProposal | None:
        pending_action = self._pending_actions.pop((session_id, user_id), None)
        if pending_action is not None:
            _ = self._pending_action_index.pop(pending_action.pending_action_id, None)
        return pending_action

    def get_pending_action_by_id(
        self, pending_action_id: str
    ) -> tuple[str, str, PendingActionProposal] | None:
        key = self._pending_action_index.get(pending_action_id)
        if key is None:
            return None
        pending_action = self._pending_actions.get(key)
        if pending_action is None:
            _ = self._pending_action_index.pop(pending_action_id, None)
            return None
        session_id, user_id = key
        return session_id, user_id, pending_action

    def reset(self, session_id: str, user_id: str | None = None) -> None:
        self._sessions[session_id] = SessionContext(session_id=session_id)
        if user_id is None:
            pending_keys = [key for key in self._pending_actions if key[0] == session_id]
            for key in pending_keys:
                pending_action = self._pending_actions.pop(key)
                _ = self._pending_action_index.pop(pending_action.pending_action_id, None)
            return
        _ = self.clear_pending_action(session_id, user_id)

    def has_processed_event(self, event_id: str) -> bool:
        return event_id in self._processed_events

    def mark_processed_event(self, event_id: str) -> None:
        self._processed_events.add(event_id)
