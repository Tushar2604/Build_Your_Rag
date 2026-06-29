from __future__ import annotations

from dataclasses import dataclass

from src.domain.shared.events import DomainEvent
from src.domain.shared.identifiers import ChatbotId, SessionId


@dataclass(frozen=True, kw_only=True)
class MessageAnswered(DomainEvent):
    session_id: SessionId
    chatbot_id: ChatbotId
    tokens_used: int
    provider: str
