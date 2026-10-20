from pydantic import BaseModel


class JoinQueueRequest(BaseModel):
    english_level: str


class JoinQueueResponse(BaseModel):
    queue_id: str
    status: str
    english_level: str


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

class CancelQueueResponse(BaseModel):
    status: str
    message: str
