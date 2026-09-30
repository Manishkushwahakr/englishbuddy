from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class ConversationParticipant(Base):
    __tablename__ = "conversation_participants"

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id"),
        primary_key=True
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        primary_key=True
    )

    conversation = relationship(
        "Conversation",
        back_populates="participants"
    )

    user = relationship(
        "User",
        back_populates="conversation_participants"
    )