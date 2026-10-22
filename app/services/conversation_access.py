from uuid import UUID

from jose import JWTError, jwt

from app.auth.security import ALGORITHM
from app.config import SECRET_KEY
from app.database import SessionLocal
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant


def authorized_conversation_user(token: str | None, conversation_id: str):
    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = UUID(payload.get("sub", ""))
        parsed_conversation_id = UUID(conversation_id)
    except (JWTError, TypeError, ValueError):
        return None

    db = SessionLocal()
    try:
        participant = (
            db.query(ConversationParticipant.user_id)
            .join(
                Conversation,
                Conversation.id == ConversationParticipant.conversation_id
            )
            .filter(
                Conversation.id == parsed_conversation_id,
                Conversation.status == "matched",
                ConversationParticipant.user_id == user_id
            )
            .first()
        )
        return str(participant[0]) if participant else None
    finally:
        db.close()
