from fastapi import APIRouter, Response
from sqlalchemy import select

from app.ai.assistant import answer
from app.api.deps import CurrentUser, DbSession, rate_limit
from app.core.exceptions import NotFoundError
from app.database.base import utcnow
from app.models.ai import AIConversation, AIMessage
from app.models.enums import MessageRole
from app.schemas.assistant import ChatRequest, ChatResponse, ConversationOut, ConversationSummary, MessageOut

router = APIRouter(prefix="/assistant", tags=["assistant"])

HISTORY_MESSAGES = 10


async def _owned(db, conversation_id: int, user_id: int) -> AIConversation:  # type: ignore[no-untyped-def]
    conv = await db.get(AIConversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise NotFoundError("Conversation not found")
    return conv


@router.post("/chat", response_model=ChatResponse, dependencies=[rate_limit("assistant", "compute_rate_limit_per_minute")])
async def chat(body: ChatRequest, user: CurrentUser, db: DbSession) -> ChatResponse:
    if body.conversation_id:
        conv = await _owned(db, body.conversation_id, user.id)
    else:
        title = body.message.strip().splitlines()[0][:80]
        conv = AIConversation(user_id=user.id, title=title)
        db.add(conv)
        await db.flush()
        await db.refresh(conv, attribute_names=["messages"])

    history = [{"role": m.role.value, "content": m.content} for m in conv.messages[-HISTORY_MESSAGES:]]
    db.add(AIMessage(conversation_id=conv.id, role=MessageRole.USER, content=body.message.strip(), meta={}))
    await db.flush()

    text, meta = await answer(db, user, body.message.strip(), history)
    reply = AIMessage(conversation_id=conv.id, role=MessageRole.ASSISTANT, content=text, meta=meta)
    db.add(reply)
    conv.updated_at = utcnow()
    await db.flush()
    return ChatResponse(conversation_id=conv.id, message=MessageOut.model_validate(reply))


@router.get("/conversations", response_model=list[ConversationSummary])
async def conversations(user: CurrentUser, db: DbSession) -> object:
    return (
        await db.scalars(
            select(AIConversation).where(AIConversation.user_id == user.id).order_by(AIConversation.updated_at.desc()).limit(50)
        )
    ).all()


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: int, user: CurrentUser, db: DbSession) -> object:
    return await _owned(db, conversation_id, user.id)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: int, user: CurrentUser, db: DbSession) -> Response:
    await db.delete(await _owned(db, conversation_id, user.id))
    return Response(status_code=204)
