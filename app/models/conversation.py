from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid

from app.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    status = Column(
        String,
        default="waiting",
        nullable=False
    )

    started_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    ended_at = Column(
        DateTime(timezone=True),
        nullable=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    participants = relationship(
        "ConversationParticipant",
        back_populates="conversation"
    )