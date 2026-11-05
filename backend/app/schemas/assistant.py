from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import MessageRole
from app.schemas.common import ORMModel


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


class MessageOut(ORMModel):
    id: int
    role: MessageRole
    content: str
    meta: dict
    created_at: datetime


class ConversationSummary(ORMModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationOut(ConversationSummary):
    messages: list[MessageOut]


class ChatResponse(BaseModel):
    conversation_id: int
    message: MessageOut
