from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case
from sqlalchemy.orm import Session, aliased
from datetime import datetime, timedelta, timezone

from app.config import (
    MATCHING_FALLBACK_WAIT_SECONDS,
    MATCHING_REPEAT_COOLDOWN_SECONDS,
)
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
    SkipPartnerRequest,
    EndConversationRequest,
    SkipAvailabilityResponse,
    MatchingStatusResponse,
    FindPartnerResponse,
    CancelQueueResponse
)


router = APIRouter(
    prefix="/matching",
    tags=["Matching"]
)

ADJACENT_LEVELS = {
    "Beginner": {"Intermediate"},
    "Intermediate": {"Beginner", "Advanced"},
    "Advanced": {"Intermediate"},
}
SKIP_LIMIT = 5
SKIP_WINDOW_SECONDS = 30 * 60
SIMULTANEOUS_SKIP_GRACE_SECONDS = 30


def latest_queue_entry(db: Session, user_id):
    return (
        db.query(MatchingQueue)
        .filter(MatchingQueue.user_id == user_id)
        .order_by(
            case(
                (MatchingQueue.status.in_(("waiting", "matched")), 1),
                else_=0
            ).desc(),
            MatchingQueue.joined_at.desc(),
            MatchingQueue.id.desc()
        )
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
            Conversation.status == "matched"
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


def has_waited_for_fallback(queue_entry, now):
    joined_at = queue_entry.joined_at
    if joined_at is None:
        return False
    if joined_at.tzinfo is None:
        joined_at = joined_at.replace(tzinfo=timezone.utc)
    return (now - joined_at).total_seconds() >= MATCHING_FALLBACK_WAIT_SECONDS


def recently_matched_partners(db: Session, user_id, now):
    if MATCHING_REPEAT_COOLDOWN_SECONDS == 0:
        return set()

    own_participant = aliased(ConversationParticipant)
    partner_participant = aliased(ConversationParticipant)
    cutoff = now - timedelta(seconds=MATCHING_REPEAT_COOLDOWN_SECONDS)
    rows = (
        db.query(partner_participant.user_id)
        .join(
            own_participant,
            own_participant.conversation_id == partner_participant.conversation_id
        )
        .join(
            Conversation,
            Conversation.id == own_participant.conversation_id
        )
        .filter(
            own_participant.user_id == user_id,
            partner_participant.user_id != user_id,
            Conversation.status.in_(("ended", "skipped")),
            Conversation.ended_at >= cutoff
        )
        .all()
    )
    return {row[0] for row in rows}


def select_partner(candidates, recent_partner_ids):
    return next(
        (
            entry for entry in candidates
            if entry.user_id not in recent_partner_ids
        ),
        candidates[0] if candidates else None
    )


def skip_history(db: Session, user_id, now):
    cutoff = now - timedelta(seconds=SKIP_WINDOW_SECONDS)
    return (
        db.query(MatchingQueue)
        .filter(
            MatchingQueue.user_id == user_id,
            MatchingQueue.status == "skipped",
            MatchingQueue.joined_at >= cutoff
        )
        .order_by(MatchingQueue.joined_at.asc())
        .all()
    )


def skip_availability(db: Session, user_id, now):
    history = skip_history(db, user_id, now)
    remaining = max(0, SKIP_LIMIT - len(history))
    retry_after = None
    if remaining == 0:
        oldest_skip = history[0].joined_at
        if oldest_skip.tzinfo is None:
            oldest_skip = oldest_skip.replace(tzinfo=timezone.utc)
        retry_after = max(
            1,
            int((oldest_skip + timedelta(seconds=SKIP_WINDOW_SECONDS) - now).total_seconds())
            + 1
        )
    return history, remaining, retry_after


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
            english_level=existing_entry.english_level,
            fallback_after_seconds=MATCHING_FALLBACK_WAIT_SECONDS
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
        english_level=queue_entry.english_level,
        fallback_after_seconds=MATCHING_FALLBACK_WAIT_SECONDS
    )


@router.post(
    "/skip",
    response_model=JoinQueueResponse
)
def skip_partner(
    data: SkipPartnerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.query(User).filter(User.id == current_user.id).with_for_update().first()
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == data.conversation_id)
        .with_for_update()
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    participant = (
        db.query(ConversationParticipant)
        .filter(
            ConversationParticipant.conversation_id == conversation.id,
            ConversationParticipant.user_id == current_user.id
        )
        .first()
    )
    if participant is None:
        raise HTTPException(
            status_code=403,
            detail="You are not a participant in this conversation"
        )

    queue_entry = latest_queue_entry(db, current_user.id)
    if queue_entry is not None and queue_entry.status == "waiting":
        db.commit()
        return JoinQueueResponse(
            queue_id=str(queue_entry.id),
            status=queue_entry.status,
            english_level=queue_entry.english_level,
            fallback_after_seconds=MATCHING_FALLBACK_WAIT_SECONDS
        )

    if queue_entry is None:
        raise HTTPException(
            status_code=409,
            detail="Your matching state changed. Return to the dashboard and search again."
        )

    now = datetime.now(timezone.utc)
    if conversation.status == "matched" and queue_entry.status != "matched":
        raise HTTPException(
            status_code=409,
            detail="Your matching state changed. Return to the dashboard and search again."
        )
    if conversation.status == "skipped":
        ended_at = conversation.ended_at
        if ended_at is None:
            raise HTTPException(
                status_code=409,
                detail="This conversation can no longer be skipped"
            )
        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=timezone.utc)
        if (
            queue_entry.status != "ended"
            or now - ended_at > timedelta(seconds=SIMULTANEOUS_SKIP_GRACE_SECONDS)
        ):
            raise HTTPException(
                status_code=409,
                detail="This conversation can no longer be skipped"
            )
    else:
        if conversation.status != "matched":
            raise HTTPException(
                status_code=409,
                detail="This conversation cannot be skipped"
            )

    if not queue_entry.english_level:
        raise HTTPException(
            status_code=409,
            detail="Your English level is missing. Return to the dashboard and search again."
        )

    history, _, retry_after = skip_availability(db, current_user.id, now)
    if len(history) >= SKIP_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Skip limit reached. You can skip again when one of your recent skips expires.",
                "retry_after_seconds": retry_after,
            }
        )

    conversation.status = "skipped"
    conversation.ended_at = now
    participant_ids = [
        row[0]
        for row in db.query(ConversationParticipant.user_id)
        .filter(ConversationParticipant.conversation_id == conversation.id)
        .all()
    ]
    db.query(MatchingQueue).filter(
        MatchingQueue.user_id.in_(participant_ids),
        MatchingQueue.status == "matched"
    ).update({"status": "ended"}, synchronize_session=False)
    queue_entry.status = "skipped"
    queue_entry.joined_at = now
    new_queue_entry = MatchingQueue(
        user_id=current_user.id,
        english_level=queue_entry.english_level,
        status="waiting"
    )
    db.add(new_queue_entry)
    db.commit()
    db.refresh(new_queue_entry)

    return JoinQueueResponse(
        queue_id=str(new_queue_entry.id),
        status=new_queue_entry.status,
        english_level=new_queue_entry.english_level,
        fallback_after_seconds=MATCHING_FALLBACK_WAIT_SECONDS
    )


@router.get(
    "/skip-status",
    response_model=SkipAvailabilityResponse
)
def get_skip_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    history, remaining, retry_after = skip_availability(db, current_user.id, now)
    return SkipAvailabilityResponse(
        limit=SKIP_LIMIT,
        window_seconds=SKIP_WINDOW_SECONDS,
        skips_used=len(history),
        skips_remaining=remaining,
        retry_after_seconds=retry_after
    )


@router.post(
    "/end",
    response_model=CancelQueueResponse
)
def end_conversation(
    data: EndConversationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.query(User).filter(User.id == current_user.id).with_for_update().first()
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == data.conversation_id)
        .with_for_update()
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    participant = (
        db.query(ConversationParticipant)
        .filter(
            ConversationParticipant.conversation_id == conversation.id,
            ConversationParticipant.user_id == current_user.id
        )
        .first()
    )
    if participant is None:
        raise HTTPException(
            status_code=403,
            detail="You are not a participant in this conversation"
        )

    if conversation.status not in {"matched", "ended"}:
        raise HTTPException(
            status_code=409,
            detail="This conversation cannot be ended"
        )

    conversation.status = "ended"
    conversation.ended_at = datetime.now(timezone.utc)
    participant_ids = [
        row[0]
        for row in db.query(ConversationParticipant.user_id)
        .filter(ConversationParticipant.conversation_id == conversation.id)
        .all()
    ]
    db.query(MatchingQueue).filter(
        MatchingQueue.user_id.in_(participant_ids),
        MatchingQueue.status == "matched"
    ).update({"status": "ended"}, synchronize_session=False)
    db.commit()

    return CancelQueueResponse(
        status="ended",
        message="The conversation has ended"
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

    now = datetime.now(timezone.utc)
    same_level_candidates = [
        entry for entry in waiting_entries
        if entry.user_id != current_user.id
        and entry.english_level == my_queue_entry.english_level
    ]
    adjacent_levels = ADJACENT_LEVELS.get(my_queue_entry.english_level, set())
    adjacent_candidates = [
        entry for entry in waiting_entries
        if entry.user_id != current_user.id
        and entry.english_level in adjacent_levels
        and has_waited_for_fallback(my_queue_entry, now)
    ]
    recent_partner_ids = recently_matched_partners(db, current_user.id, now)

    same_level_alternatives = [
        entry for entry in same_level_candidates
        if entry.user_id not in recent_partner_ids
    ]
    adjacent_alternatives = [
        entry for entry in adjacent_candidates
        if entry.user_id not in recent_partner_ids
    ]
    partner_queue_entry = (
        select_partner(same_level_alternatives, recent_partner_ids)
        or select_partner(adjacent_alternatives, recent_partner_ids)
        or select_partner(same_level_candidates, recent_partner_ids)
        or select_partner(adjacent_candidates, recent_partner_ids)
    )

    if not partner_queue_entry:
        return FindPartnerResponse(
            status="waiting",
            conversation_id=None,
            partner_id=None,
            fallback_available=bool(adjacent_candidates)
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
