"""Chatbot router."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.chat_log import ChatLog
from app.schemas.chatlog import ChatQuestion, ChatAnswer, ChatLogResponse, ChatRating
from app.services.ai_chatbot import ChatbotService

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])

_chatbot_service_instance: Optional[ChatbotService] = None


def set_chatbot_service(service: ChatbotService) -> None:
    """앱 시작 시 lifespan에서 싱글턴 서비스를 주입합니다."""
    global _chatbot_service_instance
    _chatbot_service_instance = service


def _get_chatbot_service() -> ChatbotService:
    if _chatbot_service_instance is None:
        raise RuntimeError("Chatbot service not initialized. Check app startup.")
    return _chatbot_service_instance


def _get_user_id(x_user_id: int = Header(default=1, alias="X-User-Id")) -> int:
    return x_user_id


@router.post("/ask", response_model=ChatAnswer)
async def ask_question(body: ChatQuestion, db: Session = Depends(get_db)):
    """Submit a question to the AI chatbot."""
    service = _get_chatbot_service()
    history = [h.model_dump() for h in body.history] if body.history else []
    result = await service.answer(db, question=body.question, user_id=body.user_id, history=history)
    return ChatAnswer(
        answer=result["answer"],
        intent=result["intent"],
        escalated=result["escalated"],
    )


@router.get("/history")
def get_user_history(
    user_id: int = Query(...),
    authenticated_user_id: int = Depends(_get_user_id),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """회원의 최근 대화 내역을 messages 형태로 반환."""
    if user_id != authenticated_user_id:
        raise HTTPException(status_code=403, detail="Cannot access other users' chat history")
    logs = (
        db.query(ChatLog)
        .filter(ChatLog.user_id == user_id)
        .order_by(ChatLog.created_at.asc())
        .limit(limit)
        .all()
    )
    messages = []
    for log in logs:
        messages.append({"role": "user", "text": log.question})
        messages.append({"role": "bot", "text": log.answer, "intent": log.intent, "escalated": log.escalated})
    return messages


@router.get("/logs", response_model=List[ChatLogResponse])
def list_chat_logs(
    user_id: Optional[int] = Query(None),
    intent: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List chat logs with optional filters."""
    query = db.query(ChatLog)
    if user_id is not None:
        query = query.filter(ChatLog.user_id == user_id)
    if intent:
        query = query.filter(ChatLog.intent == intent)
    return query.order_by(ChatLog.created_at.desc()).limit(limit).all()


@router.get("/logs/escalated", response_model=List[ChatLogResponse])
def list_escalated_logs(db: Session = Depends(get_db)):
    """List only escalated chat logs."""
    return (
        db.query(ChatLog)
        .filter(ChatLog.escalated.is_(True))
        .order_by(ChatLog.created_at.desc())
        .all()
    )


@router.put("/logs/{log_id}/rating", response_model=ChatLogResponse)
def rate_chat_log(log_id: int, body: ChatRating, db: Session = Depends(get_db)):
    """Rate a chatbot answer."""
    log = db.query(ChatLog).filter(ChatLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Chat log not found")
    log.rating = body.rating
    db.commit()
    db.refresh(log)
    return log
