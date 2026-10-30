import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.models.matching_queue import MatchingQueue
from app.services.transcript_session import clear_conversation_transcript


logger = logging.getLogger(__name__)


def end_conversation(
    db: Session,
    conversation_id: UUID,
    user_id: UUID,
) -> tuple[str, set[UUID], bool]:
    try:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .with_for_update()
            .first()
        )
        if conversation is None:
            return "not_found", set(), False

        participant_ids = {
            row[0]
            for row in db.query(ConversationParticipant.user_id)
            .filter(
                ConversationParticipant.conversation_id == conversation.id
            )
            .all()
        }
        if user_id not in participant_ids:
            return "forbidden", set(), False

        if conversation.status not in {"matched", "ended"}:
            return "invalid_state", participant_ids, False

        changed = conversation.status != "ended"
        if changed:
            conversation.status = "ended"
            conversation.ended_at = datetime.now(timezone.utc)

        if participant_ids:
            db.query(MatchingQueue).filter(
                MatchingQueue.user_id.in_(participant_ids),
                MatchingQueue.status == "matched",
            ).update({"status": "ended"}, synchronize_session=False)
        db.commit()
        clear_conversation_transcript(str(conversation.id))
        return "ended", participant_ids, changed
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to end conversation %s for participant %s",
            conversation_id,
            user_id,
        )
        raise
