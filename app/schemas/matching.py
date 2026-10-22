from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class JoinQueueRequest(BaseModel):
    english_level: Literal["Beginner", "Intermediate", "Advanced"]


class SkipPartnerRequest(BaseModel):
    conversation_id: UUID


class EndConversationRequest(BaseModel):
    conversation_id: UUID


class SkipAvailabilityResponse(BaseModel):
    limit: int
    window_seconds: int
    skips_used: int
    skips_remaining: int
    retry_after_seconds: int | None = None


class JoinQueueResponse(BaseModel):
    queue_id: str
    status: str
    english_level: str
    fallback_after_seconds: int = 9


class MatchingStatusResponse(BaseModel):
    status: str
    queue_id: str | None = None
    conversation_id: str | None = None
    partner_id: str | None = None
    partner_email: str | None = None
    partner_name: str | None = None


class FindPartnerResponse(BaseModel):
    status: str
    conversation_id: str | None = None
    partner_id: str | None = None
    partner_email: str | None = None
    partner_name: str | None = None
    fallback_available: bool = False

class CancelQueueResponse(BaseModel):
    status: str
    message: str
