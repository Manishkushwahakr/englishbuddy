from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.matching_queue import MatchingQueue
from app.models.user import User
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.auth.dependencies import get_current_user
from app.schemas.matching import (
    JoinQueueRequest,
    JoinQueueResponse,
    MatchingStatusResponse,
    FindPartnerResponse,
    CancelQueueResponse
)


router = APIRouter(
    prefix="/matching",
    tags=["Matching"]
)


@router.post(
    "/join",
    response_model=JoinQueueResponse
)
def join_queue(
    data: JoinQueueRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    # Check if user is already waiting
    existing_entry = (
        db.query(MatchingQueue)
        .filter(
            MatchingQueue.user_id == current_user.id,
            MatchingQueue.status == "waiting"
        )
        .first()
    )

    if existing_entry:
        raise HTTPException(
            status_code=400,
            detail="You are already in the matching queue"
        )

    # Create queue entry
    queue_entry = MatchingQueue(
        user_id=current_user.id,
        english_level=data.english_level,
        status="waiting"
    )

    db.add(queue_entry)
    db.commit()
    db.refresh(queue_entry)

    return JoinQueueResponse(
        queue_id=str(queue_entry.id),
        status=queue_entry.status,
        english_level=queue_entry.english_level
    )



@router.get(
    "/status",
    response_model=MatchingStatusResponse
)
def matching_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    queue_entry = (
        db.query(MatchingQueue)
        .filter(
            MatchingQueue.user_id == current_user.id,
            MatchingQueue.status == "waiting"
        )
        .first()
    )

    if not queue_entry:
        return MatchingStatusResponse(
            status="not_in_queue",
            queue_id=None
        )

    return MatchingStatusResponse(
        status=queue_entry.status,
        queue_id=str(queue_entry.id)
    )

@router.post(
    "/find",
    response_model=FindPartnerResponse
)
def find_partner(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Find current user's queue entry
    my_queue_entry = (
        db.query(MatchingQueue)
        .filter(
            MatchingQueue.user_id == current_user.id,
            MatchingQueue.status == "waiting"
        )
        .first()
    )

    if not my_queue_entry:
        raise HTTPException(
            status_code=400,
            detail="You are not in the matching queue"
        )

    # Find another waiting user with the same English level
    partner_queue_entry = (
        db.query(MatchingQueue)
        .filter(
            MatchingQueue.status == "waiting",
            MatchingQueue.english_level == my_queue_entry.english_level,
            MatchingQueue.user_id != current_user.id
        )
        .order_by(MatchingQueue.joined_at.asc())
        .first()
    )

    if not partner_queue_entry:
        return FindPartnerResponse(
            status="waiting",
            conversation_id=None,
            partner_id=None
        )

    # Create conversation
    conversation = Conversation(
        status="matched"
    )

    db.add(conversation)
    db.flush()

    # Add current user
    participant_1 = ConversationParticipant(
        conversation_id=conversation.id,
        user_id=current_user.id
    )

    # Add partner
    participant_2 = ConversationParticipant(
        conversation_id=conversation.id,
        user_id=partner_queue_entry.user_id
    )

    db.add(participant_1)
    db.add(participant_2)

    # Remove both users from waiting queue
    my_queue_entry.status = "matched"
    partner_queue_entry.status = "matched"

    db.commit()
    db.refresh(conversation)

    return FindPartnerResponse(
        status="matched",
        conversation_id=str(conversation.id),
        partner_id=str(partner_queue_entry.user_id)
    )


@router.post(
    "/cancel",
    response_model=CancelQueueResponse
)
def cancel_queue(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    queue_entry = (
        db.query(MatchingQueue)
        .filter(
            MatchingQueue.user_id == current_user.id,
            MatchingQueue.status == "waiting"
        )
        .first()
    )

    if not queue_entry:
        raise HTTPException(
            status_code=404,
            detail="You are not currently in the matching queue"
        )

    queue_entry.status = "cancelled"

    db.commit()

    return CancelQueueResponse(
        status="cancelled",
        message="You have left the matching queue"
    )

