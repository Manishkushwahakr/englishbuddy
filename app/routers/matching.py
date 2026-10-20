from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.matching_queue import MatchingQueue
from app.models.user import User
from app.models.profile import Profile
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


def latest_queue_entry(db: Session, user_id):
    return (
        db.query(MatchingQueue)
        .filter(MatchingQueue.user_id == user_id)
        .order_by(MatchingQueue.joined_at.desc(), MatchingQueue.id.desc())
        .first()
    )


def matched_response(db: Session, user_id, queue_entry):
    if queue_entry is None or queue_entry.status != "matched":
        return None

    conversation = (
        db.query(Conversation)
        .join(
            ConversationParticipant,
            ConversationParticipant.conversation_id == Conversation.id
        )
        .filter(
            ConversationParticipant.user_id == user_id,
            Conversation.status == "matched",
            Conversation.created_at >= queue_entry.joined_at
        )
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        .first()
    )

    if conversation is None:
        return None

    partner_participant = (
        db.query(ConversationParticipant)
        .filter(
            ConversationParticipant.conversation_id == conversation.id,
            ConversationParticipant.user_id != user_id
        )
        .first()
    )
    if partner_participant is None:
        return None

    partner = db.query(User).filter(User.id == partner_participant.user_id).first()
    if partner is None:
        return None

    profile = db.query(Profile).filter(Profile.user_id == partner.id).first()
    return {
        "status": "matched",
        "conversation_id": str(conversation.id),
        "partner_id": str(partner.id),
        "partner_email": partner.email,
        "partner_name": profile.name if profile else None,
    }


@router.post(
    "/join",
    response_model=JoinQueueResponse
)
def join_queue(
    data: JoinQueueRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    db.query(User).filter(User.id == current_user.id).with_for_update().first()

    existing_entry = (
        db.query(MatchingQueue)
        .filter(
            MatchingQueue.user_id == current_user.id,
            MatchingQueue.status.in_(("waiting", "matched"))
        )
        .order_by(MatchingQueue.joined_at.desc(), MatchingQueue.id.desc())
        .first()
    )

    if existing_entry:
        return JoinQueueResponse(
            queue_id=str(existing_entry.id),
            status=existing_entry.status,
            english_level=existing_entry.english_level
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

    queue_entry = latest_queue_entry(db, current_user.id)

    if not queue_entry:
        return MatchingStatusResponse(
            status="not_in_queue",
            queue_id=None
        )

    if queue_entry.status == "matched":
        match = matched_response(db, current_user.id, queue_entry)
        if match:
            return MatchingStatusResponse(
                queue_id=str(queue_entry.id),
                **match
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
    # Lock the waiting rows in a consistent order so concurrent polls cannot
    # create separate conversations for the same pair.
    waiting_entries = (
        db.query(MatchingQueue)
        .filter(MatchingQueue.status == "waiting")
        .order_by(MatchingQueue.joined_at.asc(), MatchingQueue.id.asc())
        .with_for_update()
        .all()
    )
    my_queue_entry = next(
        (entry for entry in waiting_entries if entry.user_id == current_user.id),
        None
    )

    if not my_queue_entry:
        queue_entry = latest_queue_entry(db, current_user.id)
        match = matched_response(db, current_user.id, queue_entry)
        if match:
            return FindPartnerResponse(**match)
        return FindPartnerResponse(
            status=queue_entry.status if queue_entry else "not_in_queue"
        )

    partner_queue_entry = next(
        (
            entry for entry in waiting_entries
            if entry.user_id != current_user.id
            and entry.english_level == my_queue_entry.english_level
        ),
        None
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

    match = matched_response(db, current_user.id, my_queue_entry)
    if match is None:
        raise HTTPException(
            status_code=500,
            detail="The conversation was created but its partner could not be loaded"
        )

    return FindPartnerResponse(**match)


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
        .order_by(MatchingQueue.joined_at.desc(), MatchingQueue.id.desc())
        .with_for_update()
        .first()
    )

    if not queue_entry:
        previous_entry = latest_queue_entry(db, current_user.id)
        if previous_entry and previous_entry.status == "matched":
            return CancelQueueResponse(
                status="matched",
                message="A partner was found before cancellation completed"
            )
        return CancelQueueResponse(
            status="cancelled",
            message="You are not currently in the matching queue"
        )

    queue_entry.status = "cancelled"

    db.commit()

    return CancelQueueResponse(
        status="cancelled",
        message="You have left the matching queue"
    )
